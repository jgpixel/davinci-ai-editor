from types import SimpleNamespace
import unittest

from analyze_recording import passage_rows, recognition_windows


class AnalysisTests(unittest.TestCase):
    def test_words_clamped_to_their_original_window(self):
        windows = [{'start': 81, 'end': 82.2}, {'start': 93.5, 'end': 94.8}]
        segments = [SimpleNamespace(seek=9350, words=[
            SimpleNamespace(start=81.7, end=93.8, word=" that's", probability=.9),
            SimpleNamespace(start=94, end=95.5, word=' good', probability=.9)])]
        row = passage_rows(segments, windows)[0]
        self.assertEqual(row['passage_id'], 1)
        self.assertEqual(row['words'][0]['start'], 93.5)
        self.assertEqual(row['words'][-1]['end'], 94.8)
        with self.assertRaisesRegex(ValueError, 'unknown speech passage'):
            passage_rows([SimpleNamespace(seek=8200, words=[])], windows)

    def test_silence_retained_in_shared_context(self):
        self.assertEqual(recognition_windows([{'start': 0, 'end': 2}, {'start': 3, 'end': 4},
                                             {'start': 8, 'end': 10}]),
                         [{'start': 0, 'end': 4}, {'start': 8, 'end': 10}])

    def test_windows_never_bridge_distant_speech_or_grow_unbounded(self):
        passages = [{'start': 0, 'end': 14}, {'start': 14.5, 'end': 28},
                    {'start': 34, 'end': 36}]
        self.assertEqual(recognition_windows(passages), passages)

    def test_empty_speech_is_valid(self):
        self.assertEqual(recognition_windows([]), [])
        self.assertEqual(passage_rows([], []), [])


if __name__ == '__main__': unittest.main()
