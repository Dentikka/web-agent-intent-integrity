"""Offline evidence inspection: integrity, path safety and metric denominators."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import artifact


class ArtifactTests(unittest.TestCase):
    def fixture(self, root: Path, unsafe: bool = False) -> None:
        section = root / 'data/cart-replication'
        section.mkdir(parents=True)
        results = [dict(error=None, model='actor', spec={'policy': 'baseline'}, scores={'valid': True}),
                   dict(error=None, model='actor', spec={'policy': 'baseline'}, scores={'valid': None}),
                   dict(error='transport failure', model='actor', spec={'policy': 'baseline'}, scores={'valid': False})]
        entries = []
        registry = []
        with zipfile.ZipFile(section / 'one.zip', 'w') as archive:
            for i, result in enumerate(results):
                name = ('../escape' if unsafe and i == 0 else f'episodes/{i}') + '/result.json'
                data = json.dumps(result).encode()
                archive.writestr(name, data)
                hashed = artifact.sha256(data)
                entries.append(dict(path=name, shard='data/cart-replication/one.zip', sha256=hashed, size=len(data)))
                registry.append(dict(cohort='fixture', source=name, artifact_sha256=hashed))
        (section / 'files.json').write_text(json.dumps(entries))
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=['cohort', 'source', 'artifact_sha256'])
        writer.writeheader()
        writer.writerows(registry)
        (section / 'trials.csv').write_text(text.getvalue())
        (section / 'index.json').write_text(json.dumps(dict(episodes=3, cohorts={'fixture': 3}, files=3,
            shards=[dict(path='data/cart-replication/one.zip', sha256=artifact.sha256((section/'one.zip').read_bytes()))])))

    def test_missing_labels_and_errors_are_not_negative_observations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with patch.object(artifact, 'ROOT', root):
                result = artifact.verify('cart-replication')
                self.assertEqual(result['technical_errors'], 1)
                artifact.summarize('cart-replication', root/'summary', ['policy'])
            cell = json.loads((root/'summary/cells.json').read_text())[0]
            self.assertEqual((cell['assigned'], cell['complete']), (3, 2))
            self.assertEqual(cell['scores']['valid'], {'k': 1, 'n': 1})

    def test_changed_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with (root/'data/cart-replication/one.zip').open('ab') as stream:
                stream.write(b'changed')
            with patch.object(artifact, 'ROOT', root), self.assertRaisesRegex(ValueError, 'checksum'):
                artifact.verify('cart-replication')

    def test_extraction_preserves_existing_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            out = root/'out'
            out.mkdir()
            (out/'keep.txt').write_text('keep')
            with patch.object(artifact, 'ROOT', root), self.assertRaisesRegex(ValueError, 'new'):
                artifact.extract('cart-replication', out)
            self.assertEqual((out/'keep.txt').read_text(), 'keep')

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root, unsafe=True)
            with patch.object(artifact, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Unsafe'):
                artifact.extract('cart-replication', root/'out')
            self.assertFalse((root/'escape').exists())


if __name__ == '__main__':
    unittest.main()
