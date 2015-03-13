# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import base64
import datetime
import hashlib
import shutil
import tempfile
import uuid

from oslo_utils import timeutils

from keystone import exception
from keystone.tests import unit as tests
from keystone.token.providers import fernet
from keystone.token.providers.fernet import token_formatters
from keystone.token.providers.fernet import utils


class KeyRepositoryTestMixin(object):
    def setUpKeyRepository(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        self.config_fixture.config(group='fernet_tokens',
                                   key_repository=directory)

        utils.create_key_directory()
        utils.initialize_key_repository()


class TestFernetTokenProvider(tests.TestCase, KeyRepositoryTestMixin):
    def setUp(self):
        super(TestFernetTokenProvider, self).setUp()
        self.setUpKeyRepository()
        self.provider = fernet.Provider()

    def test_issue_v2_token_raises_not_implemented(self):
        """Test that exception is raised when call creating v2 token."""
        token_ref = {}
        self.assertRaises(exception.NotImplemented,
                          self.provider.issue_v2_token,
                          token_ref)

    def test_validate_v2_token_raises_not_implemented(self):
        """Test that exception is raised when validating a v2 token."""
        token_ref = {}
        self.assertRaises(exception.NotImplemented,
                          self.provider.validate_v2_token,
                          token_ref)

    def test_get_token_id_raises_not_implemented(self):
        """Test that an exception is raised when calling _get_token_id."""
        token_data = {}
        self.assertRaises(exception.NotImplemented,
                          self.provider._get_token_id, token_data)

    def test_invalid_token(self):
        self.assertRaises(
            exception.Unauthorized,
            self.provider.validate_v3_token,
            uuid.uuid4().hex)


class TestBaseTokenFormatter(tests.TestCase, KeyRepositoryTestMixin):
    def setUp(self):
        super(TestBaseTokenFormatter, self).setUp()
        self.setUpKeyRepository()
        self.formatter = token_formatters.BaseTokenFormatter()

    def test_uuid_hex_to_byte_conversions(self):
        expected_hex_uuid = uuid.uuid4().hex
        uuid_obj = uuid.UUID(expected_hex_uuid)
        expected_uuid_in_bytes = uuid_obj.bytes
        actual_uuid_in_bytes = self.formatter._convert_uuid_hex_to_bytes(
            expected_hex_uuid)
        self.assertEqual(expected_uuid_in_bytes, actual_uuid_in_bytes)
        actual_hex_uuid = self.formatter._convert_uuid_bytes_to_hex(
            expected_uuid_in_bytes)
        self.assertEqual(expected_hex_uuid, actual_hex_uuid)

    def test_time_string_to_int_conversions(self):
        expected_time_str = timeutils.isotime()
        time_obj = timeutils.parse_isotime(expected_time_str)
        expected_time_int = (
            (timeutils.normalize_time(time_obj) -
             datetime.datetime.utcfromtimestamp(0)).total_seconds())

        actual_time_int = self.formatter._convert_time_string_to_int(
            expected_time_str)
        self.assertEqual(expected_time_int, actual_time_int)

        actual_time_str = self.formatter._convert_int_to_time_string(
            actual_time_int)
        self.assertEqual(expected_time_str, actual_time_str)


class TestScopedTokenFormatter(tests.TestCase, KeyRepositoryTestMixin):
    def setUp(self):
        super(TestScopedTokenFormatter, self).setUp()
        self.setUpKeyRepository()
        self.formatter = token_formatters.ScopedTokenFormatter()

    def test_token_encryption(self):
        exp_user_id = uuid.uuid4().hex
        exp_project_id = uuid.uuid4().hex
        # All we are validating here is that the token is encrypted and
        # decrypted properly, not the actual validity of token data.
        exp_expires_at = timeutils.isotime(timeutils.utcnow())
        exp_audit_ids = base64.urlsafe_b64encode(uuid.uuid4().bytes)[:-2]

        token = self.formatter.create_token(
            exp_user_id, exp_project_id, exp_expires_at, exp_audit_ids)

        (user_id, project_id, expires_at, audit_ids) = (
            self.formatter.validate_token(token[len('F00'):]))

        self.assertEqual(exp_user_id, user_id)
        self.assertEqual(exp_project_id, project_id)
        self.assertEqual(exp_expires_at, expires_at)
        self.assertEqual(exp_audit_ids, audit_ids)

    def test_encrypted_token_is_under_255_characters(self):
        user_id = uuid.uuid4().hex
        project_id = uuid.uuid4().hex
        # All we are validating here is that the token is encrypted and
        # decrypted properly, not the actual validity of token data.
        encrypted_token = self.formatter.create_token(
            user_id,
            project_id,
            timeutils.isotime(timeutils.utcnow()),
            base64.urlsafe_b64encode(uuid.uuid4().bytes)[:-2])
        self.assertLess(len(encrypted_token), 255)


class TestCustomTokenFormatter(TestScopedTokenFormatter):
    def setUp(self):
        # bypassing the parent setUp because we want to set up our own custom
        # token formatter
        super(TestScopedTokenFormatter, self).setUp()

        class HandRolledCrypto(object):
            """Hold my beer and watch this."""
            def encrypt(self, plaintext):
                """Adds security by obscurity."""
                checksum = hashlib.md5(plaintext).hexdigest()
                return '%s-%s' % (plaintext[::-1], checksum)

            def decrypt(self, ciphertext):
                """Removes obscurity to validate security."""
                try:
                    ciphertext, checksum = ciphertext.rsplit('-', 1)
                except ValueError:
                    raise exception.Unauthorized()
                plaintext = ciphertext[::-1]
                if checksum != hashlib.md5(plaintext).hexdigest():
                    raise exception.Unauthorized()
                return plaintext

        class CustomTokenFormatter(token_formatters.ScopedTokenFormatter):
            @property
            def crypto(self):
                """Customize the cryptography implementation."""
                return HandRolledCrypto()

        self.formatter = CustomTokenFormatter()


class TestTrustTokenFormatter(tests.TestCase, KeyRepositoryTestMixin):
    def setUp(self):
        super(TestTrustTokenFormatter, self).setUp()
        self.setUpKeyRepository()
        self.formatter = token_formatters.TrustTokenFormatter()

    def test_encrypted_trust_token_is_under_255_characters(self):
        user_id = uuid.uuid4().hex
        project_id = uuid.uuid4().hex

        encrypted_token = self.formatter.create_token(
            user_id,
            project_id,
            timeutils.isotime(timeutils.utcnow()),
            base64.urlsafe_b64encode(uuid.uuid4().bytes)[:-2],
            uuid.uuid4().hex)
        self.assertLess(len(encrypted_token), 255)