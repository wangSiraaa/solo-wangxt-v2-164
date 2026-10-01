"""受限规则表达式 DSL 的单测：白名单安全 + 语义。"""
from django.test import SimpleTestCase

from pricing.rules_lang import (
    RuleContextError,
    RuleSyntaxError,
    evaluate,
    evaluate_bool,
)


class DslTests(SimpleTestCase):
    def test_basic_logic_and_arithmetic(self):
        ctx = {"stay_days": 4, "stopovers": 0, "transfers": 1}
        self.assertTrue(evaluate_bool("stay_days >= 3 and stay_days <= 14", ctx))
        self.assertTrue(evaluate_bool("stopovers <= 0 and transfers <= 2", ctx))
        self.assertFalse(evaluate_bool("stay_days < 3", ctx))
        self.assertEqual(evaluate("2 + 3 * 4", {}), 14)
        self.assertTrue(evaluate_bool("not (stay_days < 3)", ctx))
        self.assertTrue(evaluate_bool("stay_days == None or stay_days >= 3",
                                      {"stay_days": None}))

    def test_membership_and_dotted_dict(self):
        ctx = {"component": {"rbd": "Y"}, "all_rbds": ["Y", "Q"]}
        self.assertTrue(evaluate_bool('component.rbd in ["Y", "B"]', ctx))
        self.assertTrue(evaluate_bool('"Q" in all_rbds', ctx))
        self.assertFalse(evaluate_bool('component.rbd == "Q"', ctx))

    def test_allowed_helpers(self):
        ctx = {"xs": [1, 2, 3]}
        self.assertEqual(evaluate("len(xs)", ctx), 3)
        self.assertEqual(evaluate("max(xs)", ctx), 3)
        self.assertEqual(evaluate("min(xs)", ctx), 1)
        self.assertTrue(evaluate_bool("all([True, 1, 3])", ctx))
        self.assertTrue(evaluate_bool("any([False, 0, 2])", ctx))

    def test_generator_comprehension_rejected(self):
        with self.assertRaises(RuleSyntaxError):
            evaluate("all(x > 0 for x in xs)", {"xs": [1, 2]})

    def test_attribute_escape_blocked(self):
        # 不能借 __class__ 等属性逃逸出上下文字典。
        with self.assertRaises(RuleContextError):
            evaluate("x.__class__", {"x": {"a": 1}})

    def test_builtin_and_import_blocked(self):
        with self.assertRaises((RuleSyntaxError, RuleContextError)):
            evaluate("__import__('os').system('echo hi')", {})
        with self.assertRaises(RuleContextError):
            evaluate("open", {})

    def test_arbitrary_call_blocked(self):
        with self.assertRaises(RuleSyntaxError):
            evaluate("evil()", {"evil": lambda: True})

    def test_unknown_name_is_context_error(self):
        with self.assertRaises(RuleContextError):
            evaluate_bool("nope == 1", {})

    def test_bad_syntax(self):
        with self.assertRaises(RuleSyntaxError):
            evaluate("stay_days >=", {"stay_days": 1})
