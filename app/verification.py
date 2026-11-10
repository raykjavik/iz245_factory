"""Delegate acceptance policies to the domain configuration modules.

Policies receive a measurement and return True, False, or None (not evaluated).
Some tests require measured data only; others check numerical acceptance limits.
Only True makes a verification LED green.
"""

import cfg_test1
import cfg_test2
import cfg_test3
import cfg_test4
import cfg_test_5_6
import cfg_test_7
import cfg_test8


def evaluate_test1(measurement):
    return cfg_test1.evaluate_test1(measurement)


def evaluate_test2(measurement):
    return cfg_test2.evaluate_test2(measurement)


def evaluate_test3(measurement):
    return cfg_test3.evaluate_test3(measurement)


def evaluate_test4(measurement):
    return cfg_test4.evaluate_test4(measurement)


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
    return cfg_test_5_6.evaluate_test5(measurement)


def evaluate_test6(measurement):
    return cfg_test_5_6.evaluate_test6(measurement)


def evaluate_test7(measurement):
    return cfg_test_7.evaluate_test7(measurement)


def evaluate_test8(measurement):
    return cfg_test8.evaluate_test8(measurement)
