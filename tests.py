import json
import unittest

from base64 import b64encode
from copy import copy
from itertools import product
from time import time

from Crypto.PublicKey import RSA
from Crypto.Cipher import AES

import jose 

rsa_key = RSA.generate(2048)

rsa_priv_key = {
    'k': rsa_key.exportKey('PEM'),
}
rsa_pub_key = {
    'k': rsa_key.publickey().exportKey('PEM'), 
}

claims = {'john': 'cleese'}


class TestSerializeDeserialize(unittest.TestCase):
    def test_serialize(self):
        invalid = '1.2.3.4'

        try:
            jose.deserialize_compact('1.2.3.4')
            self.fail()
        except ValueError as e:
            self.assertEqual(e.message, 'Malformed JWT')


class TestJWE(unittest.TestCase):
    encs = ('A128CBC-HS256', 'A192CBC-HS384', 'A256CBC-HS512')
    algs = (('RSA-OAEP', rsa_key),)

    def test_jwe(self):
        bad_key = {'k': RSA.generate(2048).exportKey('PEM')}

        for (alg, jwk), enc in product(self.algs, self.encs):
            jwe = jose.encrypt(claims, rsa_pub_key, enc=enc, alg=alg)

            # make sure the body can't be loaded as json (should be encrypted)
            try:
                json.loads(jose.b64decode_url(jwe.ciphertext))
                self.fail()
            except ValueError:
                pass

            token = jose.serialize_compact(jwe)

            jwt = jose.decrypt(jose.deserialize_compact(token), rsa_priv_key)

            self.assertEqual(jwt.claims, claims)

            # invalid key
            try:
                jose.decrypt(jose.deserialize_compact(token), bad_key)
                self.fail()
            except ValueError as e:
                self.assertEqual(e.message, 'Incorrect decryption.')

    def test_jwe_add_header(self):
        add_header = {'foo': 'bar'}

        for (alg, jwk), enc in product(self.algs, self.encs):
            et = jose.serialize_compact(jose.encrypt(claims, rsa_pub_key,
                add_header=add_header))
            jwt = jose.decrypt(jose.deserialize_compact(et), rsa_priv_key)

            self.assertEqual(jwt.header['foo'], add_header['foo'])

    def test_jwe_adata(self):
        adata = '42'
        for (alg, jwk), enc in product(self.algs, self.encs):
            et = jose.serialize_compact(jose.encrypt(claims, rsa_pub_key,
                adata=adata))
            jwt = jose.decrypt(jose.deserialize_compact(et), rsa_priv_key,
                    adata=adata)

            # make sure signaures don't match when adata isn't passed in
            try:
                hdr, dt = jose.decrypt(jose.deserialize_compact(et),
                    rsa_priv_key)
                self.fail()
            except ValueError as e:
                self.assertEqual(e.message, 'Mismatched authentication tags')

            self.assertEqual(jwt.claims, claims)

    def test_jwe_invalid_dates_error(self):
        claims = {'exp': time() - 5}
        et = jose.serialize_compact(jose.encrypt(claims, rsa_pub_key))

        try:
            jose.decrypt(jose.deserialize_compact(et), rsa_priv_key)
            self.fail() # expecting expired token
        except ValueError:
            pass


        claims = {'nbf': time() + 5}
        et = jose.serialize_compact(jose.encrypt(claims, rsa_pub_key))

        try:
            jose.decrypt(jose.deserialize_compact(et), rsa_priv_key)
            self.fail() # expecting not valid yet
        except ValueError:
            pass

    def test_jwe_compression(self):
        local_claims = copy(claims)

        for v in xrange(1000):
            local_claims['dummy_' + str(v)] = '0' * 100

        jwe = jose.serialize_compact(jose.encrypt(local_claims, rsa_pub_key))
        _, _, _, uncompressed_ciphertext, _ = jwe.split('.')

        jwe = jose.serialize_compact(jose.encrypt(local_claims, rsa_pub_key,
            compression='DEF'))
        _, _, _, compressed_ciphertext, _ = jwe.split('.')

        self.assertTrue(len(compressed_ciphertext) <
                len(uncompressed_ciphertext))

        jwt = jose.decrypt(jose.deserialize_compact(jwe), rsa_priv_key)
        self.assertEqual(jwt.claims, local_claims)

    def test_encrypt_invalid_compression_error(self):
        try:
            jose.encrypt(claims, rsa_pub_key, compression='BAD')
            self.fail()
        except ValueError:
            pass

    def test_decrypt_invalid_compression_error(self):
        jwe = jose.encrypt(claims, rsa_pub_key, compression='DEF')
        header = jose.b64encode_url('{"alg": "RSA-OAEP", '
            '"enc": "A128CBC-HS256", "zip": "BAD"}')

        try:
            jose.decrypt(jose.JWE(*((header,) + (jwe[1:]))), rsa_priv_key)
            self.fail()
        except ValueError as e:
            self.assertEqual(e.message,
                    'Unsupported compression algorithm: BAD')


class TestJWS(unittest.TestCase):

    def test_jws_sym(self):
        algs = ('HS256', 'HS384', 'HS512',)
        jwk = {'k': 'password'}

        for alg in algs:
            st = jose.serialize_compact(jose.sign(claims, jwk, alg=alg))
            jwt = jose.verify(jose.deserialize_compact(st), jwk)

            self.assertEqual(jwt.claims, claims)

    def test_jws_asym(self):
        algs = ('RS256', 'RS384', 'RS512')

        for alg in algs:
            st = jose.serialize_compact(jose.sign(claims, rsa_priv_key, alg=alg))
            jwt = jose.verify(jose.deserialize_compact(st), rsa_pub_key)
            self.assertEqual(jwt.claims, claims)

    def test_jws_signature_mismatch_error(self):
        jwk = {'k': 'password'}
        jws = jose.sign(claims, jwk)
        try:
            jose.verify(jose.JWS(jws.header, jws.payload, 'asd'), jwk)
        except ValueError as e:
            self.assertEqual(e.message, 'Mismatched signatures')


class TestUtils(unittest.TestCase):
    def test_b64encode_url_utf8(self):
        istr = 'eric idle'.encode('utf8')
        encoded = jose.b64encode_url(istr)
        self.assertEqual(jose.b64decode_url(encoded), istr)

    def test_b64encode_url_ascii(self):
        istr = 'eric idle'
        encoded = jose.b64encode_url(istr)
        self.assertEqual(jose.b64decode_url(encoded), istr)

    def test_b64encode_url(self):
        istr = '{"alg": "RSA-OAEP", "enc": "A128CBC-HS256"}'

        # sanity check
        self.assertEqual(b64encode(istr)[-1], '=')

        # actual test
        self.assertNotEqual(jose.b64encode_url(istr), '=')


class TestJWA(unittest.TestCase):
    def test_lookup(self):
        impl = jose._JWA._impl
        jose._JWA._impl = dict((k, k) for k in (
            'HS256', 'RSA-OAEP', 'A128CBC', 'A128CBC'))

        self.assertEqual(jose.JWA['HS256'], 'HS256')
        self.assertEqual(jose.JWA['RSA-OAEP'], 'RSA-OAEP')
        self.assertEqual(jose.JWA['A128CBC-HS256'],
                ('A128CBC', 'HS256'))
        self.assertEqual(jose.JWA['A128CBC+HS256'],
                ('A128CBC', 'HS256'))

        jose._JWA._impl = impl

    def test_invalid_error(self):
        try:
            jose.JWA['bad']
        except KeyError as e:
            self.assertTrue(e.message.startswith('Unsupported'))


if __name__ == '__main__':
    unittest.main()
