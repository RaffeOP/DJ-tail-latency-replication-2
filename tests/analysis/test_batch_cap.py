import unittest

from analysis.batch_cap import transfer_cap


class TransferCapTest(unittest.TestCase):
    def test_default_cap_is_clamped_at_thirty_two_for_small_objects(self):
        self.assertEqual(transfer_cap(64, 64 * 1024, 32), 32)

    def test_default_cap_halves_as_objects_grow(self):
        self.assertEqual(transfer_cap(16384, 64 * 1024, 32), 4)

    def test_default_cap_floors_at_two_objects(self):
        self.assertEqual(transfer_cap(262144, 64 * 1024, 32), 2)

    def test_patched_cap_uses_one_mebibyte_budget(self):
        self.assertEqual(transfer_cap(16384, 1024 * 1024, 256), 64)


if __name__ == "__main__":
    unittest.main()
