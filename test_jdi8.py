import unittest
import sys
from dataset_manager.utils.jdi8 import calculate_jdi8

# Reconfigure stdout to use UTF-8
sys.stdout.reconfigure(encoding='utf-8')

class TestJDI8Scoring(unittest.TestCase):
    
    def test_jappa_soup(self):
        # 鱈のじゃっぱ汁: Cod, Radish, Carrot, Scallion, Miso
        # Should match: Miso, Seaweed (from kelp/dashi in text), green/yellow veg (carrot/scallion), fish (cod), low meat (no beef/pork)
        name = "鱈のじゃっぱ汁"
        main = "タラ、大根、人参、ねぎ、味噌"
        recipe_ing = "出汁昆布 1本\nタラのじゃっぱ 1～1.5kg\n大根 1本\n人参 1本\n味噌 適量\nねぎ 2本"
        
        res = calculate_jdi8(name, main, recipe_ing)
        
        self.assertTrue(res['miso'])
        self.assertTrue(res['seaweed'])  # matches "出汁昆布"
        self.assertTrue(res['green_yellow_veg'])  # matches "人参", "ねぎ"
        self.assertTrue(res['fish'])  # matches "タラ", "出汁昆布"
        self.assertTrue(res['low_meat'])  # True because no meat keywords are present
        
        # Check total score (should be at least 5)
        self.assertGreaterEqual(res['score'], 5)
        print(f"Test Cod Jappa Soup JDI8 Score: {res['score']}/8 (Matched: {list(res['evidence'].keys())})")

    def test_beef_stew(self):
        # Beef stew contains beef
        name = "牛肉の煮込み"
        main = "牛肉、大根"
        
        res = calculate_jdi8(name, main)
        
        self.assertFalse(res['low_meat'])  # False because beef is present
        print(f"Test Beef Stew Low Meat check: {res['low_meat']} (Score: {res['score']})")

    def test_tea_rice(self):
        # Match tea and rice
        name = "鯛茶漬け"
        main = "ご飯、鯛、緑茶"
        
        res = calculate_jdi8(name, main)
        
        self.assertTrue(res['rice'])
        self.assertTrue(res['green_tea'])
        self.assertTrue(res['fish'])
        print(f"Test Sea Bream Tea Rice JDI8 Score: {res['score']}/8")

if __name__ == '__main__':
    unittest.main()
