"""Delegate acceptance policies to the domain configuration modules.

Policies receive a measurement and return True, False, or None (not evaluated).
Some tests require measured data only; others check numerical acceptance limits.
Only True makes a verification LED green.
"""


def evaluate_test1(measurement):
    from cfg_test1 import evaluate_test1 as evaluate
    return evaluate(measurement)


def evaluate_test2(measurement):
    from cfg_test2 import evaluate_test2 as evaluate
    return evaluate(measurement)


def evaluate_test3(measurement):
    from cfg_test3 import evaluate_test3 as evaluate
    return evaluate(measurement)


def evaluate_test4(measurement):
    from cfg_test4 import evaluate_test4 as evaluate
    return evaluate(measurement)


def evaluate_verification(measurement):
    """Dispatch by the TEST1_, TEST2_, or TEST3_ measurement name prefix."""
    if measurement.name.startswith('TEST8_'):
        return evaluate_test8(measurement)
    if measurement.name.startswith('TEST7_'):
        return evaluate_test7(measurement)
    if measurement.name.startswith('TEST1_'):
        return evaluate_test1(measurement)
    if measurement.name.startswith('TEST2_'):
        return evaluate_test2(measurement)
    if measurement.name.startswith('TEST3_'):
        return evaluate_test3(measurement)
    if measurement.name == 'TEST4' or measurement.name.startswith('TEST4_'):
        return evaluate_test4(measurement)
    return None


def evaluate_test5(measurement):
    from cfg_test_5_6 import evaluate_test5 as evaluate
    return evaluate(measurement)


def evaluate_test6(measurement):
    from cfg_test_5_6 import evaluate_test6 as evaluate
    return evaluate(measurement)


def evaluate_test7(measurement):
    from cfg_test_7 import evaluate_test7 as evaluate
    return evaluate(measurement)


def evaluate_test8(measurement):
    from cfg_test8 import evaluate_test8 as evaluate
    return evaluate(measurement)
