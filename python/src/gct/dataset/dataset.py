from gct import utils, config
import fastparquet
import json 
import numpy as np
import pandas as pd  
import os
import sys
import glob
from gct.utils import TempDir
from fnmatch import fnmatch


class Clustering(object):
    '''
    A clustering (or partition) of a graph. May be disjointed or overlapped. The partitions in the clustering are also called clusters.  
    '''

    def __init__(self, clusteringobj):
        self.logger = utils.get_logger("{}".format(type(self).__name__))
        self.cluster = None 
        self.path = None 
        from gct.alg.clustering import Result
        if isinstance(clusteringobj, str):
            self.path = utils.abspath(clusteringobj)
        elif isinstance(clusteringobj, Result):
            self.cluster = clusteringobj.clustering(as_dataframe=True)
        elif isinstance(clusteringobj, dict):
            if 'clusters' in clusteringobj: # a dict result
                self.cluster = Result(clusteringobj).clustering(as_dataframe=True)
            else: # assume it is a dict(cluster_id, list[node])
                arr = np.array([[u,v] for u,vv in clusteringobj.items() for v in vv ])
                if len(arr.shape) != 2 or arr.shape[1] != 2:
                    raise ValueError("arg is not right")
                self.cluster = pd.DataFrame(arr, columns=['node', 'cluster'])
        elif isinstance(clusteringobj, pd.DataFrame):
            if not 'cluster' in clusteringobj.columns or not 'node' in clusteringobj.columns:
                raise ValueError("arg is not right")
            self.cluster = clusteringobj[['node', 'cluster']]
        else:  
            if isinstance(clusteringobj, list):
                arr = np.array(clusteringobj)
            elif isinstance(clusteringobj, np.ndarray):
                arr = clusteringobj  
            else:
                raise ValueError("arg is not right")
            if len(arr.shape) != 2 or arr.shape[1] != 2:
                raise ValueError("arg is not right")
            self.cluster = pd.DataFrame(arr, columns=['node', 'cluster'])
        if self.cluster is not None:
            self.cluster = self.cluster.drop_duplicates()

    def persistent_cnl(self):
        if self.path is not None:
            local_cnl = self.path + ".cnl"
            if not utils.file_exists(local_cnl):
                self.logger.info("persistent cluster to cnl file: " + local_cnl)
                self.save_to_cnl_file(local_cnl)
            return local_cnl                                         
        return None 
    
    # filepath will be overwritten
    def save_to_cnl_file(self, filepath):
        '''
        save the clustering to a cnl format file.
        
        :param filepath: where to save
        '''
        df = self.value()
        with open(filepath, 'wt') as f :
            for lst in df.groupby('cluster')['node'].apply(lambda u: list(u)):
                line = " ".join([str(u) for u in lst]) + "\n"
                f.write(line)
        return filepath 
    
    # if persistent cnl exists, it will be linked to filepath, otherwise write clsuters to filepath  
    def make_cnl_file(self, filepath=None):
        local_cnl = self.persistent_cnl()
        if local_cnl:
            return utils.link_file(local_cnl, destname=filepath)
        else:
            assert filepath is not None 
            return self.save_to_cnl_file(filepath)
                
    def is_persistent(self):
        return self.path is not None  and utils.file_exists(self.path)

    @property 
    def index(self):
        """
        :rtype: cluster ids
        """
        prop_name = "_" + sys._getframe().f_code.co_name 

        def f():
            df = self.value()
            return np.unique(df['cluster'].values)

        return utils.set_if_not_exists(self, prop_name, f)

    @property 
    def num_cluster(self):
        '''
        number of clusters
        '''
        return len(self.index)
    
    @property 
    def is_overlap(self):
        """
        :rtype: True if the clusters are overlapped
        """
        prop_name = "_" + sys._getframe().f_code.co_name 

        def f():
            return (self.node_overlaps > 1).any()

        return utils.set_if_not_exists(self, prop_name, f)
    
    @property 
    def node_overlaps(self):
        '''
        :rtype: overlapping count of each node.
        '''
        prop_name = "_" + sys._getframe().f_code.co_name 

        def f():
            df = self.value()
            return df.groupby('node')['cluster'].count()

        return utils.set_if_not_exists(self, prop_name, f)
        
    def persistent(self, filepath=None, force=False):
        assert not (self.path is  None  and filepath is None)
        if filepath is None:
            if force: 
                self.save(self.path)
            else:
                raise Exception("already persistent")
        else:
            if self.path is None:
                self.path = utils.abspath(filepath)
                self.save(self.path)
            else:
                if utils.path_equals(self.path, filepath):
                    if force: 
                        self.save(self.path)
                    else:
                        raise Exception("already persistent")
             
    def save(self, filepath, format="parq"):
        '''
        save the cluster to a file
        
        :param filepath: where to save.
        :param format: 'parq' or 'csv'
        
        '''
        assert filepath 
        self.logger.info("Writing " + filepath)
        if format == "parq":
            fastparquet.writer.write(filepath, self.value(), compression="SNAPPY")
        elif format == "csv":
            self.value().to_csv(filepath, index=None)
        else:
            raise ValueError("Error: " + format) 
        
    def value(self, erase_overlap=False):
        '''
        :rtype: Pandas dataframe of clustering
        '''
        ret = None
        if self.cluster is not None: 
            ret= self.cluster
        else:
            self.logger.info("reading" + self.path)
            df = fastparquet.ParquetFile(self.path).to_pandas()
            self.cluster = df 
            if self.cluster is not None:
                self.cluster = self.cluster.drop_duplicates()            
            ret = self.cluster
        if not erase_overlap:
            return ret 
        else:
            fn = lambda obj: obj.loc[np.random.choice(obj.index, 1, False),:]
            return ret.groupby('node', as_index=False).apply(fn)

        
class Dataset(object):
    '''
    A dataset represents a graph and optional one or more ground truth. 
    The graph is either directed or undirected, weighted or unweighted. 
    The ground truth is either disjointed or overlapped.
    
    Every dataset has a name. Once created it saved on local disk (under $GCT_DATA).  
    
    Instead of construct a dataset directly, mostly one creates a dataset use other methods, e.g. :py:meth:`gct.load_dataset`, 
    :py:meth:`gct.from_snap`, :py:meth:`gct.from_igraph`, :py:meth:`gct.from_networkx`, :py:meth:`gct.from_networkit`
    
    There are also building graphs that can be loaded directly. Use :py:meth:`gct.list_dataset` to find them.
    '''

    def __init__(self, name=None, description="", groundtruthObj=None, edgesObj=None, directed=False,
                 weighted=False, overide=False, additional_meta=None, is_edge_mirrored=False):
        assert edgesObj is not None 
        self.name = name 
        self.description = description
        self.additional_meta = additional_meta
        self.logger = utils.get_logger("{}:{}".format(type(self).__name__, self.name))
        self.directed = directed 
        self.weighted = weighted
        self.is_edge_mirrored = is_edge_mirrored
         
        self.parq_edges = None
         
        if name:
            assert name 
            self.file_edges = config.get_data_file_path(self.name, 'edges.txt')
            self.file_pajek = config.get_data_file_path(self.name, 'pajek.txt')
            self.file_hig = config.get_data_file_path(self.name, 'pajek.hig')
            self.file_scanbin = config.get_data_file_path(self.name, 'scanbin')
            self.file_anyscan = config.get_data_file_path(self.name, 'anyscan.txt')
            self.file_snap = config.get_data_file_path(self.name, 'snap.bin')
            self.file_mcl_mci = config.get_data_file_path(self.name, 'mcl.mci')
            self.file_mcl_tab = config.get_data_file_path(self.name, 'mcl.tab')
            self.file_topgc = config.get_data_file_path(self.name, 'topgc.txt')
            self.file_mirror_edges = config.get_data_file_path(self.name, 'edges_mirror.txt')
            
            if self.is_weighted():
                self.file_unweighted_edges = self.file_edges
            else:
                self.file_unweighted_edges = config.get_data_file_path(self.name, 'unweighted_edges.txt')
                    
        self.set_ground_truth(groundtruthObj)
        self.set_edges(edgesObj)
        
        if name:
            is_persistent = self.is_edges_persistent() and self.is_ground_truth_persistent()
            self.home = config.get_data_file_path(name, create=False)
            if utils.file_exists(self.home):
                if overide:
                    utils.remove_if_file_exit(self.home, is_dir=True)
                elif is_persistent:
                    pass 
                else:
                    raise Exception("Dataset {} exists at {}. Use overide=True or load it locally.".format(name, self.home))
            
            if not is_persistent:
                utils.remove_if_file_exit(config.get_result_file_path(self.name), is_dir=True)                               
                utils.create_dir_if_not_exists(self.home) 
                self.persistent()
                self.update_meta()
        
    def is_edges_persistent(self):
        return hasattr(self, "parq_edges") and self.parq_edges is not None and utils.file_exists(self.parq_edges)        
    
    def persistent(self):
        if not self.is_edges_persistent():
            filepath = config.get_data_file_path(self.name, 'edges.parq')
            self.persistent_edges(filepath)
        if self.has_ground_truth():
            for k, v in self.get_ground_truth().items():
                if not v.is_persistent():
                    filepath = config.get_data_file_path(self.name, 'gt_{}.parq'.format(k))                
                    v.persistent(filepath)
                
    def persistent_edges(self, filepath=None, force=False):
        assert not (self.parq_edges is  None  and filepath is None)
        if filepath is None:
            if force: 
                self.save_edges(self.path)
            else:
                raise Exception("already persistent")
        else:
            if self.parq_edges is None:
                self.parq_edges = utils.abspath(filepath)
                self.save_edges(self.parq_edges)
            else:
                if utils.path_equals(self.parq_edges, filepath):
                    if force: 
                        self.save_edges(self.parq_edges)
                    else:
                        raise Exception("already persistent")
        
    def save_edges(self, filepath, format="parq"):
        assert filepath 
        self.logger.info("writing" + filepath)
        if format == "parq":
            fastparquet.writer.write(filepath, self.get_edges(), compression="SNAPPY")
        elif format == "csv":
            self.value().to_csv(filepath, index=None)
        else:
            raise ValueError("Error: " + format)
                
    def __repr__(self, *args, **kwargs):
        return self.__str__()
    
    def get_meta(self):
        d = {'name': self.name ,
            'weighted': self.is_weighted(),
             'has_ground_truth':self.has_ground_truth(),
             'directed': self.is_directed(),
             'is_edge_mirrored':self.is_edge_mirrored}
        d['parq_edges'] = self.parq_edges
        
        if self.has_ground_truth():
            d['parq_ground_truth'] = {u:v.path for u, v in self.get_ground_truth().items()}
        if self.additional_meta:
            d.update({"additional": self.additional_meta})
        d['description'] = self.description
        return d 
    
    def is_anonymous(self):
        return False if self.name else True
    
    def update_meta(self):
        if not self.is_anonymous():
            meta_file = config.get_data_file_path(self.name, 'meta.info')
            json.dump(self.get_meta(), open(meta_file, 'wt')) 

    def is_ground_truth_persistent(self):
        if self.has_ground_truth():
            for v in self.get_ground_truth().values():
                if not v.is_persistent():
                    return False 
        return True 

    def set_ground_truth(self, obj):
        if obj is None: return 

        def to_clustering(v):
            if isinstance(v, Clustering):
                return v 
            else:
                return Clustering(v)
        
        if isinstance(obj, dict):
            self.ground_truth = {u:to_clustering(v) for u, v in obj.items()}
        elif isinstance(obj, tuple):
            self.ground_truth = {"cluster" + str(u):to_clustering(v) for u, v in enumerate(obj)}
        else:
            self.ground_truth = {"default":to_clustering(obj)}

    @property 
    def num_node_edge(self):

        def f():
            df = self.get_edges()
            m = len(df)
            n = len(set(np.unique(self.edges[['src', 'dest']].values)))
            return (n, m)

        prop_name = "_num_node_edge"        
        return utils.set_if_not_exists(self, prop_name, f)

    @property 
    def num_node(self):
        return self.num_node_edge[0]

    @property 
    def num_edge(self):
        return self.num_node_edge[1]
        
    def set_edges(self, obj):
        v = obj
        if isinstance(v, str):
            self.parq_edges = utils.abspath(v)
            return self 
        else:
            if isinstance(v, pd.DataFrame):
                if not 'src' in v.columns or not 'dest' in v.columns or (self.is_weighted() and 'weight' not in v.columns):
                    raise ValueError("arg is not right")
                if self.is_weighted():
                    self.edges = v[['src', 'dest', 'weight']]
                else:
                    self.edges = v[['src', 'dest']]
            else:  
                if isinstance(v, list):
                    arr = np.array(v)
                elif isinstance(v, np.ndarray):
                    arr = v
                else:
                    raise ValueError("arg is not a list, ndarray or dataframe")
                if len(arr.shape) != 2  or arr.shape[1] != 2 + int(self.is_weighted()):
                    raise ValueError("data shape is not correct: " + str(arr.shape))
                if self.is_weighted():
                    self.edges = pd.DataFrame(arr, columns=['src', 'dest', 'weight'])
                else:
                    self.edges = pd.DataFrame(arr, columns=['src', 'dest'])
                    
            def clean_edges():
                edges = self.edges
                if self.is_weighted():
                    assert 'weight' in edges.columns
                else:
                    assert 'weight' not in edges.columns

                edges['src'] = edges['src'].astype(np.int)
                edges['dest'] = edges['dest'].astype(np.int)
                if self.is_weighted(): 
                    edges['weight'] = edges['weight'].astype(np.float32)

                if not self.is_edge_mirrored and not self.is_directed():
                    edges1 = edges[edges['src'] <= edges['dest']]
                    edges2 = edges[edges['src'] > edges['dest']]
                    edges2.rename(columns={'src': 'dest', 'dest': 'src'}, inplace=True)
                    edges = pd.concat([edges1, edges2[edges1.columns]], axis=0)
                self.edges = edges

            clean_edges()
            
            self.edges = self.edges.drop_duplicates()
            num_edge = len(self.edges)
            num_node = len(np.unique(self.edges[['src', 'dest']].values.ravel()))
            self._num_node_edge = (num_node, num_edge)
            return self 

    def __str__(self, *args, **kwargs):
        d = self.get_meta()
        return json.dumps(d)
        
    def has_ground_truth(self):
        return hasattr(self, 'ground_truth') and self.ground_truth is not None 
    
    def is_directed(self):
        return  self.directed 
    
    def is_weighted(self):
        return self.weighted
    
    # return edge list
    def get_edges(self):
        if not hasattr(self, 'edges'):
            self.logger.info("reading " + self.parq_edges)
            self.edges = fastparquet.ParquetFile(self.parq_edges).to_pandas() 
        return self.edges            
    
    # return
    def get_ground_truth(self):
        if self.has_ground_truth():
            return self.ground_truth
        return None 
 
    def to_edgelist(self, filepath=None, sep=" ", sort=False):
        if (filepath == None):
            filepath = self.file_edges
            if utils.file_exists(filepath):
                return filepath 
        self.logger.info("writing edges to " + filepath)
        with open(filepath, 'wt') as f :
            columns = ['src', 'dest', 'weight'] if self.is_weighted() else ['src', 'dest']
            df = self.get_edges()[columns]
            if sort:
                df = df.sort_values(by=['src', 'dest'])
            for i in range(df.shape[0]):
                r = df.iloc[i]
                r = ['%g' % (u) for u in r ]
                row = sep.join(r)  
                row += "\n"
                f.write(row)
        self.logger.info("finish writing " + filepath)                
        return filepath 

    def to_snapformat(self, filepath=None):
        if (filepath == None):
            filepath = self.file_snap 
            if utils.file_exists(filepath):
                return filepath
        
        import snap        
        from gct.dataset import convert
        g = convert.to_snap(self)
        self.logger.info("Writing {} to {}".format(type(g), filepath))
        FOut = snap.TFOut(filepath)
        g.Save(FOut)
        FOut.Flush()
        
        return filepath 
        
    def to_pajek(self, filepath=None):
        if (filepath == None):
            filepath = self.file_pajek
            if utils.file_exists(filepath):
                return filepath             
        if not utils.file_exists(self.file_edges): self.to_edgelist()
        from gct.dataset import edgelist2pajek
        edgelist2pajek.edgelist_to_pajek(self.file_edges, self.file_pajek , self.is_directed(), self.is_weighted())
        return filepath 

    def to_scanbin(self, filepath=None):
        if (filepath == None):
            filepath = self.file_scanbin
            if utils.file_exists(os.path.join(filepath, "b_degree.bin")) and utils.file_exists(os.path.join(filepath, "b_adj.bin")):
                return filepath         
            utils.create_dir_if_not_exists(filepath)    
        if not utils.file_exists(self.file_edges): self.to_edgelist()
        cmd = "{} {} {} {}".format(config.SCAN_CONVERT_PROG, self.file_edges, "b_degree.bin", "b_adj.bin")
        self.logger.info("running " + cmd)
        status = utils.shell_run_and_wait(cmd, filepath)
        if (status != 0):
            raise Exception("run command failed: " + str(status))
        return filepath 

    def to_mcl_mci(self, filepath=None):
        if (filepath == None):
            filepath = self.file_mcl_mci
            if utils.file_exists(filepath):
                return filepath         
        if not utils.file_exists(self.file_edges): self.to_edgelist()
        if not self.is_directed():
            cmd = "{} --stream-mirror -123 {} -o {} --write-binary".format(config.MCL_CONVERT_PROG, self.file_edges, filepath)
        else:
            cmd = "{} -123 {} -o {} --write-binary".format(config.MCL_CONVERT_PROG, self.file_edges, filepath)
        self.logger.info("running " + cmd)
        status = utils.shell_run_and_wait(cmd)
        if (status != 0):
            raise Exception("run command failed: " + str(status))
        return filepath 

    def to_anyscan(self, filepath=None):
        if False and self.is_directed():
            raise Exception("directed graph not supported")
        if (filepath == None):
            filepath = self.file_anyscan
            if utils.file_exists(filepath):
                return filepath
            
        edges1 = self.get_edges()[['src', 'dest']]
        min_node = min(edges1['src'].min(), edges1['dest'].min())
        max_node = max(edges1['src'].max(), edges1['dest'].max())
        self.logger.info("min node: {}, max node: {}".format(min_node, max_node))
        if min_node != 0  :
            self.logger.warn("node id is greater than 0, fake node will be added")

        self_edges = pd.DataFrame([[u, u] for u in range(max_node + 1)], columns=['src', 'dest'])
        edges2 = edges1[['dest', 'src']].copy();  edges2.columns = ['src', 'dest']
        edges = pd.concat([edges1, edges2, self_edges], axis=0)
        del edges1, edges2, self_edges 

        def fun(df):
            values = sorted(list(set(df['dest'])))
            return str(len(values)) + " " + " ".join([str(u) for u in values])

        grouped = edges.groupby('src').apply(fun).reset_index()
        with open(filepath, 'wt') as f:
            f.write(str(max_node + 1) + "\n")
            for i in grouped.index: 
                f.write(grouped.loc[i, 0] + "\n")
        return filepath 

    def to_higformat(self, filepath=None):
        if (filepath == None):
            filepath = self.file_hig
            if utils.file_exists(filepath):
                return filepath         
        if not utils.file_exists(self.file_pajek): self.to_pajek()
        
        cmd = "python {} {}".format(config.HIG_CONVERT_PROG, self.file_pajek)
        self.logger.info("running " + cmd)
        status = utils.shell_run_and_wait(cmd)
        if (status != 0):
            raise Exception("run command failed: " + str(status))
        return filepath 

    def to_unweighted_fromat(self, filepath=None):
        if (filepath == None):
            filepath = self.file_unweighted_edges
            if utils.file_exists(filepath):
                return filepath         
        edges = self.get_edges()[['src', 'dest']]
        edges.to_csv(filepath, header=None, index=None, sep=" ")
        return filepath 

    def to_topgc_fromat_backup(self, filepath=None):
        if (filepath == None):
            filepath = self.file_topgc
            if utils.file_exists(filepath):
                return filepath         
        if not utils.file_exists(self.file_mirror_edges): self.to_mirror_edges_format()
        with TempDir() as tmp_dir:
            cmd = "cat {} | {} >  {} || rm {}".format(self.file_mirror_edges, config.get_cdc_prog('mkidx'),
                                                  filepath, filepath)
            self.logger.info("Running " + cmd)
            with open(os.path.join(tmp_dir, "tmpcmd"), 'wt') as f :
                f.write(cmd)
            
            timecost, status = utils.timeit(lambda: utils.shell_run_and_wait("bash -x tmpcmd", tmp_dir))
            if status != 0: 
                raise Exception("Run command with error status code {}".format(status))
        assert utils.file_exists(filepath)
        return filepath 

    def to_topgc_fromat(self, filepath=None):
        if (filepath == None):
            filepath = self.file_topgc
            if utils.file_exists(filepath):
                return filepath         
        if not utils.file_exists(self.file_edges): self.to_edgelist()
        with TempDir() as tmp_dir:
            cmd = "cat {}|sort -k1,1 -k2,2 -n | {} >  {} || rm {}".format(self.file_edges, config.get_cdc_prog('mkidx'),
                                                  filepath, filepath)
            self.logger.info("Running " + cmd)
            with open(os.path.join(tmp_dir, "tmpcmd"), 'wt') as f :
                f.write(cmd)
            
            timecost, status = utils.timeit(lambda: utils.shell_run_and_wait("bash -x tmpcmd", tmp_dir))
            if status != 0: 
                raise Exception("Run command with error status code {}".format(status))
        assert utils.file_exists(filepath)
        return filepath 

    def to_mirror_edges_format(self, filepath=None):
        if (filepath == None):
            filepath = self.file_mirror_edges
            if utils.file_exists(filepath):
                return filepath         
        edges1 = self.get_edges()
        edges2 = edges1.copy()
        edges2['src'] = edges1['dest']
        edges2['dest'] = edges1['src']
        edges2 = edges2[edges1.columns]
        edges = pd.concat([edges1, edges2]).drop_duplicates().sort_values(['src', 'dest'])
        edges.to_csv(filepath, header=None, index=None, sep=" ")
        return filepath 
        
    ##### to third party graph 
    def to_graph_igraph(self):
        from gct.dataset import convert 
        return convert.to_igraph(self)
    
    def to_graph_networkx(self):
        from gct.dataset import convert 
        return convert.to_networkx(self)
    
    def to_graph_snap(self):
        from gct.dataset import convert 
        return convert.to_snap(self)
    def to_graph_tool_graph(self):
        from gct.dataset import convert 
        return convert.to_graph_tool(self)
        
    def to_coo_adjacency_matrix(self):
        from gct.dataset import convert 
        return convert.to_coo_adjacency_matrix(self)            
    
    def as_undirected(self, newname, description="", overide=False):
        from gct.dataset import convert
        return convert.as_undirected(self, newname=newname, description=description, overide=overide)
        
    def as_unweight(self, newname, description="", overide=False):
        from gct.dataset import convert
        return convert.as_unweighted(self, newname=newname, description=description, overide=overide)
    
    def as_unweight_undirected(self, newname, description="", overide=False):
        from gct.dataset import convert
        return convert.as_unweighted_undirected(self, newname=newname, description=description, overide=overide)

    def as_mirror_edges(self, newname, description="", overide=False):
        from gct.dataset import convert
        return convert.as_mirror_edges(self, newname=newname, description=description, overide=overide)


def local_exists(name):
    '''
    check if dataset 'name' exists locally.
    
    :param name: name of a dataset
    :rtype: bool
    '''
    path = config.get_data_file_path(name)
    return  utils.file_exists(path)


def list_local():
    '''
    list all local datasets
    '''
    path = config.DATA_PATH
    return [os.path.basename(u[:-1])  for u in glob.glob(path + "/*/")]


def remove_local(name, rm_graph_data=True, rm_clustering_result=True):
    '''
    remove a local dataset 

    :param name: name of a dataset
    :param rm_clustering_result: remove local graph data
    :param rm_clustering_result: remove clustering results associated with the graph.
    '''
    if rm_graph_data:
        path = config.get_data_file_path(name)
        utils.remove_if_file_exit(path, is_dir=True)
    if rm_clustering_result:
        path = config.get_result_file_path(name)
        utils.remove_if_file_exit(path, is_dir=True)


def create_dataset(name, edgesObj, groundtruthObj=None, directed=False, weighted=False, description="", overide=False):
    return Dataset(name=name, edgesObj=edgesObj, groundtruthObj=groundtruthObj, directed=directed, weighted=weighted, \
                    description=description, overide=overide)                

    
def load_local(name):
    '''
    load a local dataset
    
    :param name: name of a dataset 
    '''
    path = config.get_data_file_path(name, create=False)
    if not utils.file_exists(path):
        raise Exception("path not exists: " + path)
    with open(os.path.join(path, 'meta.info')) as f:
        meta = json.load(f)
    edges = meta['parq_edges']
    gt = None 
    if meta["has_ground_truth"]:
        gt = {k:Clustering(v) for k, v in meta['parq_ground_truth'].items()}
    additional_meta = None if not "additional" in meta else meta['additional'] 
    is_edge_mirrored = meta['is_edge_mirrored']
    return Dataset(name=meta['name'], description=meta['description'], groundtruthObj=gt, edgesObj=edges, directed=meta['directed'],
                    weighted=meta['weighted'], overide=False, additional_meta=additional_meta, is_edge_mirrored=is_edge_mirrored)

    
def list_clustering(dataset_name):
    '''
    list clustering results associated with the dataset
    
    :param dataset_name: name of a dataset 
    '''
    path = config.get_result_file_path(dataset_name)
    return [os.path.basename(u[:-1])  for u in glob.glob(path + "/*/")]


def list_all_clustering(print_format=False):
    '''
    list clustering results associated with all available datasets
    
    '''
        
    ret = {}
    for dsname in list_local():
        ret[dsname] = list_clustering(dsname)
    if print_format:
        return ["{}/{}".format(u, v) for u, vv in ret.items() for v in vv ]
    else:
        return ret 

    
def list_dataset(pattern=None):
    '''
    list dataset matching the pattern. The pattern supports Unix shell-style wildcards. For example
    
    .. doctest::
    
        >>> import gct
        >>> for v in gct.list_dataset('*snap*'):
        ...     print (v)
        ... 
        ('snap', 'com-DBLP')
        ('snap', 'com-LiveJournal')
        
    lists two datasets in the format of (category, name), which can be used to invoke :py:meth:`gct.load_dataset`
    
    '''
    ret = []
    cat = 'local'
    names = list_local()
    for name in names:
        ret.append((cat, name))
        
    cat = 'snap'
    from gct.dataset import snap_dataset 
    names = snap_dataset.list_datasets()
    for name in names:
        ret.append((cat, name))        

    cat = 'sample'
    from gct.dataset import sample_dataset 
    names = sample_dataset.list_datasets()
    for name in names:
        ret.append((cat, name))
        
    ret = [u for u in ret if pattern is None or fnmatch(str(u), pattern)]
    return sorted(ret)

    
def load_dataset(name, cat=None):
    '''
    load a named dataset. If catetory is not specified, all available datasets will be searched.

    :param name: name of the dataset
    :param cat: category of the dataset 
    :rtype: :py:class:`gct.Dataset` a dataset 
    :raises: Exception
 
    '''
    cats = ['local', 'snap', 'sample']
    assert cat is None or cat in cats, "category is not found"
    if cat is not None: cats = [cat]
    for cat in cats:
        if cat == 'local' and local_exists(name):
            return load_local(name)
        elif cat == 'snap':
            from gct.dataset import snap_dataset
            if name in snap_dataset.list_datasets():
                return snap_dataset.load_snap_dataset(name)
        elif cat == 'sample':
            from gct.dataset import sample_dataset
            if name in sample_dataset.list_datasets():
                return sample_dataset.load_sample_dataset(name)
    raise Exception("data '{}' not found".format(name))
    
