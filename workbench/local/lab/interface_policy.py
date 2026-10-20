"""Single source of truth for how a (problem, language) pair is executed.

Before this module the answer was spread over three places: pipeline_jobs branched
on a literal string, problem_packages.code_interface derived it, and the
rejudge/resume resolver re-implemented it. Whenever the interface was missing or
unfamiliar, every one of those silently took the portable branch -- and the
portable driver can resolve a helper function, turning "wrong target function,
correct helper" into a false Accepted.

Rules here:
  * a known interface is used as recorded;
  * a missing interface is re-derived from the problem package, and the derivation
    is recorded, never hidden;
  * an unknown interface blocks. It never degrades to another entry.
"""
from __future__ import annotations

NATIVE = 'leetcode_method'
PORTABLE_DRIVER = None  # filled lazily from portable_drivers.VERSION
SQL = ('mysql', 'sqlite')
SHELL = ('bash',)

NATIVE_ROUTE = 'native'
SQL_ROUTE = 'sql'
SHELL_ROUTE = 'shell'
PORTABLE_ROUTE = 'portable'


class UnknownInterface(Exception):
    """The execution entry cannot be established, so no verdict may be issued."""

    def __init__(self, interface, origin):
        self.interface = interface
        self.origin = origin
        super().__init__('未知或缺失的执行接口 %r（来源：%s）' % (interface, origin))


def known():
    from local.lab import portable_drivers
    return frozenset({NATIVE, portable_drivers.VERSION} | set(SQL) | set(SHELL))


def route(interface):
    if interface == NATIVE:
        return NATIVE_ROUTE
    if interface in SQL:
        return SQL_ROUTE
    if interface in SHELL:
        return SHELL_ROUTE
    return PORTABLE_ROUTE


def resolve(pair, derive=None):
    """Return (interface, origin).

    origin is 'frozen' when the record already carried it, or
    'derived_from_package' when it had to be re-derived. Both are legitimate; the
    difference is recorded so a derivation is never mistaken for a frozen fact.
    """
    interface = (pair or {}).get('interface')
    if interface:
        if interface not in known():
            raise UnknownInterface(interface, 'frozen')
        return interface, 'frozen'
    if derive is None:
        raise UnknownInterface(None, 'frozen')
    derived = derive()
    if not derived or derived not in known():
        raise UnknownInterface(derived, 'derived_from_package')
    return derived, 'derived_from_package'
