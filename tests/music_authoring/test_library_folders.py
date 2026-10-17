"""Exercise folder metadata through the real player bundler."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from music_authoring.library_player import LibraryError, build_entry


class LibraryFolderTests(unittest.TestCase):
    def entry(self, **extra):
        return dict(id='basic', name='Basic',
            source=str(ROOT / 'examples/music_authoring/basic/song.json'),
            preview=str(ROOT / 'examples/music_authoring/basic/preview'), **extra)

    def test_explicit_folder_survives_bundle(self):
        result = build_entry(self.entry(folder='My tracks', category='Teaching'), ROOT, 0)
        self.assertEqual(result['folder'], 'My tracks')
        self.assertEqual(result['category'], 'Teaching')
        self.assertTrue(result['wav_sha256'])

    def test_legacy_category_and_unfiled_fallback(self):
        self.assertEqual(build_entry(self.entry(category='Teaching'), ROOT, 0)['folder'], 'Teaching')
        self.assertEqual(build_entry(self.entry(), ROOT, 0)['folder'], 'Other')

    def test_invalid_folders_have_actionable_catalog_error(self):
        for value in [None, 12, [], '', '  ']:
            with self.subTest(value=value), self.assertRaises(LibraryError) as caught:
                build_entry(self.entry(folder=value), ROOT, 3)
            self.assertEqual(caught.exception.code, 'CATALOG_INVALID')
            self.assertEqual(caught.exception.path, '/entries/3/folder')


if __name__ == '__main__':
    unittest.main()
