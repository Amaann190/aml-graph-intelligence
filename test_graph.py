import unittest
import pandas as pd
from analyze import score_day

class GraphRules(unittest.TestCase):
    def test_time_direction_distinct_degree_and_self_edges(self):
        edges = [("A", str(i), "09:00") for i in range(10)]
        edges += [(str(i), "B", "09:00") for i in range(10)]
        edges += [("0", "A", "10:00"), ("A", "A", "11:00")]
        edges += [("X", "Y", "09:00")] * 12 + [("Y", "X", "09:00")]
        out = score_day(pd.DataFrame(edges, columns=["source", "target", "time"]))
        self.assertEqual(len(out), 21)
        self.assertEqual(out.fan_in.sum(), 10)
        self.assertEqual(out.fan_out.sum(), 10)
        self.assertEqual(list(out.index[out.return_transfer]), [20])
