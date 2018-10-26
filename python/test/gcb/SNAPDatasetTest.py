'''
Created on Oct 23, 2018

@author: lizhen
'''
import unittest
from gcb import dataset, random_dataset


class Test(unittest.TestCase):

    def testLoadDataset(self):
        for name in dataset.list_datasets():
            if name in ['com-DBLP']:
                ds = dataset.get_dataset(name)
                print ds  
                ds.load()


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testLoadSNAPDataset']
    unittest.main()