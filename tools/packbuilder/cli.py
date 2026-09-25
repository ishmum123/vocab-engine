"""Command line: python3 -m packbuilder <command> --lang <code> --repo <path>

    build   run the pipeline (optionally up to one --stage) into <repo>/pack
    check   pack-level schema, coverage and language assertions (exit 1 on failure)
    scan    the QA scans (gloss junk, articles/closed sets, non-lemmas)
    sample  stratified word / sentence samples for hand QA (--seed)
    passages  <repo>: tools/passages_src.json -> pack/passages.json (--check: report only);
              <repo> may be a flat pack dir (packs/zh: passages_src.json -> passages.json beside it)
"""
import argparse

from .langs import get_spec


def main(argv=None):
    ap = argparse.ArgumentParser(prog="packbuilder", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--lang", required=True, help="language code (packbuilder/langs/<code>.py)")
        p.add_argument("--repo", default=".", help="language repo root (holds pack/, tools/, .cache/)")
        return p

    from .core.pipeline import STAGES
    b = common(sub.add_parser("build", help="build pack/*.json and tools/REPORT.md"))
    b.add_argument("--stage", default="all", choices=STAGES)
    b.add_argument("--check-remote", action="store_true",
                   help="re-download sources whose remote size changed")
    common(sub.add_parser("check", help="pack-level checks"))
    s = common(sub.add_parser("scan", help="QA scans over pack/"))
    s.add_argument("--only", choices=["1", "2", "3"], help="run one scan")
    sm = common(sub.add_parser("sample", help="stratified hand-QA samples"))
    sm.add_argument("--seed", type=int, required=True)
    sm.add_argument("--words", type=int, default=60)
    sm.add_argument("--sentences", type=int, default=60)
    pg = sub.add_parser("passages", help="reading passages: tools/passages_src.json -> pack/passages.json")
    pg.add_argument("repo", help="language repo root, or a flat pack dir (packs/zh)")
    pg.add_argument("--lang", help="language code (default: pack/pack.json key)")
    pg.add_argument("--check", action="store_true", help="report coverage/validation only, write nothing")
    args = ap.parse_args(argv)

    if args.cmd == "passages":
        from .passages import main as passages_main
        return passages_main(args.repo, args.lang, args.check)

    spec = get_spec(args.lang, args.repo)
    if args.cmd == "build":
        from .core.pipeline import run
        from .core.util import Env
        run(Env(spec), args.stage, args.check_remote)
        return 0
    if args.cmd == "check":
        from .qa.check import check
        return check(spec)
    if args.cmd == "scan":
        from .qa.scans import run_scans
        return run_scans(spec, args.only)
    if args.cmd == "sample":
        from .qa.sample import sample
        return sample(spec, args.seed, args.words, args.sentences)
    return 2
