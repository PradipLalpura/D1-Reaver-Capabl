"""Token admin: python scripts/tokens.py issue LABEL [CAP] | revoke LABEL | usage."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.tokens import issue, revoke, usage


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("issue", "revoke", "usage"):
        print(__doc__.strip())
        return
    if sys.argv[1] == "issue":
        cap = int(sys.argv[3]) if len(sys.argv) > 3 else 500
        print(issue(sys.argv[2] if len(sys.argv) > 2 else "manual", cap))
    elif sys.argv[1] == "revoke":
        print("revoked:", revoke(sys.argv[2]))
    else:
        for row in usage():
            print("%(label)s | cap %(cap)d | used %(used)d | %(day)s | %(revoked)s" % row)


if __name__ == "__main__":
    main()
