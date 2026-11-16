import copy
import unittest

from tools.shadow_tool_evidence import require_rejection


class ToolEvidenceTests(unittest.TestCase):
    def test_exact_name_all_errors_and_advertised_inventory(self):
        good = [{'advertised': ['DeferredToolPlaceholder', 'StructuredOutput'],
                 'tool_results': [{'error': True, 'content': 'No such tool available: Task.'}]}]
        require_rejection('Task', 'failed-closed', False, good, False)
        wrong_name = copy.deepcopy(good)
        wrong_name[0]['tool_results'][0]['content'] = 'No such tool available: TaskOutput'
        dotted_name = copy.deepcopy(good)
        dotted_name[0]['tool_results'][0]['content'] = 'No such tool available: Task.Output'
        mixed = copy.deepcopy(good)
        mixed[0]['tool_results'].append({'error': False, 'content': 'executed'})
        extra = copy.deepcopy(good)
        extra[0]['advertised'].append('Bash')
        missing = copy.deepcopy(good)
        missing[0]['advertised'].remove('DeferredToolPlaceholder')
        for bad in [wrong_name, dotted_name, mixed, extra, missing]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                require_rejection('Task', 'failed-closed', False, bad, False)

    def test_rejection_is_required_not_merely_observed(self):
        records = [{'advertised': ['DeferredToolPlaceholder', 'StructuredOutput'],
                    'tool_results': [{'error': True, 'content': 'No such tool available: Bash'}]}]
        require_rejection('Bash', 'failed-closed', False, records, False)
        for status, marker, output in [('accepted', False, False), ('failed-closed', True, False),
                                       ('failed-closed', False, True)]:
            with self.subTest(status=status, marker=marker, output=output), self.assertRaises(ValueError):
                require_rejection('Bash', status, marker, records, output)
        for bad in [[], [{'advertised': [], 'tool_results': []}],
                    [{'advertised': ['DeferredToolPlaceholder', 'StructuredOutput'], 'tool_results': []}]]:
            with self.assertRaises(ValueError):
                require_rejection('Bash', 'failed-closed', False, bad, False)
        for field, value in [('error', False), ('content', 'No such tool available: Read')]:
            bad = copy.deepcopy(records)
            bad[0]['tool_results'][0][field] = value
            with self.assertRaises(ValueError):
                require_rejection('Bash', 'failed-closed', False, bad, False)
