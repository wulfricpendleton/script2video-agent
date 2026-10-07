import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]))
from agent.runner import Agent
class T(unittest.TestCase):
 def test_plan_and_budget(self):
  p=Agent().plan(["a","b"]);self.assertEqual(p[0]["model"],"seedance-2.5");self.assertEqual(Agent().budget(p),1.96)
if __name__=="__main__":unittest.main()
