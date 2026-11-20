"""Pure width-policy tests; native QWidget geometry is verified separately."""
import unittest

from hdw_person_lens.personlens_theme import initial_split_sizes


class SplitterSizingTests(unittest.TestCase):
    def test_initial_ratio(self):
        self.assertEqual(initial_split_sizes(1920), (864, 1056))
        self.assertEqual(initial_split_sizes(1000), (450, 550))

    def test_no_negative_size(self):
        self.assertEqual(initial_split_sizes(-50), (0, 0))

    def test_total_is_preserved(self):
        for width in (1, 320, 701, 1133, 1921):
            self.assertEqual(sum(initial_split_sizes(width)), width)
