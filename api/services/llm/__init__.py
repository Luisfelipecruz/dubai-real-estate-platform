"""The generation layer.

Everything under here is OPTIONAL at runtime. `LLM_PROVIDER=none` disables the whole
package, `POST /ask` reports 503, and the platform's 30 other REST operations are
unaffected -- which is asserted in api/tests/test_main.py, not assumed.
"""
