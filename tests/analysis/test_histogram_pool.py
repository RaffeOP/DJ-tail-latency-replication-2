import unittest

from analysis.histogram_pool import pool_buckets, total_count, weighted_mean, weighted_percentile


class HistogramPoolTest(unittest.TestCase):
    def test_pool_buckets_sums_counts_per_representative(self):
        pooled = pool_buckets([[[10, 3], [20, 1]], [[10, 2], [30, 5]]])
        self.assertEqual(pooled, [(10, 5), (20, 1), (30, 5)])

    def test_total_count_adds_all_counts(self):
        self.assertEqual(total_count([(10, 5), (20, 1)]), 6)

    def test_percentile_uses_ceiling_rank(self):
        buckets = [(10, 90), (100, 9), (1000, 1)]
        self.assertEqual(weighted_percentile(buckets, 99.0), 100)
        self.assertEqual(weighted_percentile(buckets, 99.9), 1000)

    def test_percentile_of_empty_histogram_is_zero(self):
        self.assertEqual(weighted_percentile([], 99.9), 0)

    def test_weighted_mean_respects_counts(self):
        self.assertAlmostEqual(weighted_mean([(10, 3), (20, 1)]), 12.5)


if __name__ == "__main__":
    unittest.main()
