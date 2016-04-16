#!/usr/bin/env python3


import sys

import Avi


def test_avi(stream):
    a = Avi.AviInput(stream, debug=True)
    print(a.get_frame(0))


def main():
    with open(sys.argv[1], "rb") as stream:
        test_avi(stream)


if __name__ == '__main__':
    main()
