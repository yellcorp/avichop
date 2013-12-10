#!/usr/bin/python


import sys

import Avi


def test_avi(stream):
	a = Avi.AviFile(stream, debug=True)
	a.parse()


def main():
	with open(sys.argv[1], "rb") as stream:
		test_avi(stream)


if __name__ == '__main__':
	main()
