import unittest

from board import cues


class CuesTest(unittest.TestCase):
    def test_table(self):
        cases = {
            "Ram I will address later so park it for now": "park",
            "side note to add to the next steps": "park",
            "add a follow up task to set up DNS": "park",
            "Flag this for me": "park",
            "do it later please": "park",
            "btw can I ssh in?": "btw",
            "By the way, what is the port?": "btw",
            "the later version is fine": None,
            "park the car": None,
            "follow the steps": None,
            "": None,
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(cues.match(text), want)


if __name__ == "__main__":
    unittest.main()
