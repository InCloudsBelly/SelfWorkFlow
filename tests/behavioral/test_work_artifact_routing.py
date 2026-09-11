import unittest

from selfworkflow.work_artifacts import lifecycle_hook_required


class WorkArtifactRoutingTests(unittest.TestCase):
    def test_light_single_document_does_not_create_lifecycle(self):
        self.assertFalse(lifecycle_hook_required("Light", 0))
        self.assertFalse(lifecycle_hook_required("Light", 1))

    def test_full_deep_and_multi_document_tasks_use_lifecycle(self):
        self.assertTrue(lifecycle_hook_required("Full", 0))
        self.assertTrue(lifecycle_hook_required("Deep", 0))
        self.assertTrue(lifecycle_hook_required("Light", 2))


if __name__ == "__main__":
    unittest.main()
