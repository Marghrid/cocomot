#!/usr/bin/env python3
"""Export the interval (symbolic) cluster representatives of a log to a new XES,
preserving ALL original event/trace data.

The clustering itself runs on stripped {label, valuation} traces, so we map each
representative back to its ORIGINAL pm4py trace (by object identity) and write the
untouched original -- keeping timestamps, resources and every other attribute.

Usage:
  python3 scripts/export_clusters.py <model.pnml> <log.xes> <out.xes> [--no-count-attr] [--naive-only]

  --no-count-attr   do not add the additive cocomot:cluster_size trace attribute
  --naive-only      stop after the naive partitioning stage (exact activity
                    sequence + valuation); skip the interval/symbolic stage
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pm4py.objects.log.obj import EventLog
from pm4py.objects.log.exporter.xes import exporter as xes_exporter

from dpn.read import read_pnml_input
from dpn.dpn import DPN
from cocomot import read_log, preprocess_trace
from cluster.partitioning import NaivePartitioning, IntervalPartitioning


def profile(traces):
  """Collect, per attribute key, the set of value type-names ("kinds") and the
  set of distinct hashable values -- at both event and trace level."""
  ev_kinds, ev_vals, tr_kinds, tr_vals = {}, {}, {}, {}
  for t in traces:
    for k, v in t.attributes.items():
      tr_kinds.setdefault(k, set()).add(type(v).__name__)
      try:
        tr_vals.setdefault(k, set()).add(v)
      except TypeError:
        pass
    for e in t:
      for k, v in e.items():
        ev_kinds.setdefault(k, set()).add(type(v).__name__)
        try:
          ev_vals.setdefault(k, set()).add(v)
        except TypeError:
          pass
  return ev_kinds, ev_vals, tr_kinds, tr_vals


def report(level, o_kinds, o_vals, c_kinds, c_vals, ignore_keys=()):
  ok = True
  print("\n--- %s-level attributes ---" % level)
  missing_keys = [k for k in o_kinds if k not in c_kinds and k not in ignore_keys]
  print("  keys: original=%d compact=%d" % (len(o_kinds), len(c_kinds)))
  if missing_keys:
    ok = False
    print("  !! KEYS MISSING FROM COMPACT: %s" % sorted(missing_keys))
  else:
    print("  keys missing from compact: none  OK")

  print("  value-kind (type) check per key:")
  kind_loss = False
  for k in sorted(o_kinds):
    if k in ignore_keys:
      continue
    miss = o_kinds[k] - c_kinds.get(k, set())
    if miss:
      kind_loss = True
      ok = False
      print("    !! %-28s lost kinds %s (orig %s)" % (k, sorted(miss), sorted(o_kinds[k])))
  if not kind_loss:
    print("    no value-kinds lost  OK")

  print("  distinct-value coverage per key (informational):")
  for k in sorted(o_vals):
    if k in ignore_keys:
      continue
    o, c = o_vals[k], c_vals.get(k, set())
    lost = o - c
    tag = "" if not lost else "  e.g. %s" % list(lost)[:3]
    print("    %-28s %d/%d distinct kept, %d not represented%s" %
          (k, len(o & c), len(o), len(lost), tag))
  return ok


def main():
  if len(sys.argv) < 4:
    print(__doc__)
    sys.exit(1)
  model, logpath, outpath = sys.argv[1], sys.argv[2], sys.argv[3]
  add_count = "--no-count-attr" not in sys.argv[4:]
  naive_only = "--naive-only" in sys.argv[4:]

  dpn = DPN(read_pnml_input(model))
  (log, _unc) = read_log(logpath)
  n_orig = len(log)
  print("read %d traces from %s" % (n_orig, logpath))

  # stripped trace -> original pm4py trace, preserving order
  simple_by_id = {}
  entries = []
  for orig in log:
    s = preprocess_trace(orig, dpn)
    simple_by_id[id(s)] = orig
    entries.append((s, 1))

  naive = NaivePartitioning(entries)
  if naive_only:
    reps = naive.partitions
    print("clusters: naive=%d (naive-only, interval stage skipped)" %
          naive.partition_count())
  else:
    interval = IntervalPartitioning(dpn, naive.representatives())
    reps = interval.partitions
    print("clusters: naive=%d interval=%d" %
          (naive.partition_count(), interval.partition_count()))

  out = EventLog(
    attributes=getattr(log, "attributes", {}),
    extensions=getattr(log, "extensions", {}),
    classifiers=getattr(log, "classifiers", {}),
    omni_present=getattr(log, "omni_present", {}),
  )
  covered = 0
  for (simple_rep, count) in reps:
    orig = simple_by_id[id(simple_rep)]
    if add_count:
      orig.attributes["cocomot:cluster_size"] = count
    out.append(orig)
    covered += count

  xes_exporter.apply(out, outpath)
  print("wrote %d representatives to %s, covering %d traces" %
        (len(out), outpath, covered))

  # ---- verification (uses in-memory logs, no reload) ----
  print("\n================ VERIFICATION ================")
  print("representatives N = %d" % len(out))
  print("coverage sum = %d  (original = %d): %s" %
        (covered, n_orig, "OK" if covered == n_orig else "MISMATCH"))
  o_ek, o_ev, o_tk, o_tv = profile(log)
  c_ek, c_ev, c_tk, c_tv = profile(out)
  # the count attribute we add is expected to be extra on the compact side
  ok_ev = report("event", o_ek, o_ev, c_ek, c_ev)
  ok_tr = report("trace", o_tk, o_tv, c_tk, c_tv, ignore_keys=("cocomot:cluster_size",))
  print("\nVERDICT: %s" %
        ("all keys & value-kinds preserved" if (ok_ev and ok_tr)
         else "SOME KEYS OR VALUE-KINDS LOST (see !! above)"))


if __name__ == "__main__":
  main()
