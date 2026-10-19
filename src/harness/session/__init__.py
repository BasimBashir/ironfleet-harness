# src/harness/session/__init__.py
"""The R3 session shell's package: store (JSONL + index + jobs), workspace
isolation, the factory executor, visibility readers, the D-T3 token meter, and
the Textual app. The shell rides the gate/proxy/scheduler substrate — this
package never opens its own model connection."""
