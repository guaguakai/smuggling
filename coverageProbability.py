# -*- coding: utf-8 -*-
"""
Created on Tue Apr 30 01:25:29 2019

@author: Aditya
"""
from scipy.optimize import minimize 
import networkx as nx
import numpy as np
import time
# import autograd.numpy as np
from numpy.linalg import *
from graphData import *
import torch
import autograd
from gurobipy import *

REG = 0.01
MEAN_REG = 0.00

def phi2prob(G, phi): # unbiased but no need to be normalized. It will be normalized later
    N=nx.number_of_nodes(G)
    adj = torch.Tensor(nx.adjacency_matrix(G).toarray())
    adj_phi = adj * phi - (1 - adj) * 100 # adding -100 to all the non-adjacent entries
    unbiased_probs = torch.nn.Softmax(dim=1)(adj_phi)
    unbiased_probs = unbiased_probs * adj

    # unbiased_probs = adj * torch.exp(phi)
    # unbiased_probs = unbiased_probs / torch.sum(unbiased_probs, keepdim=True, dim=1)
    # unbiased_probs[torch.isnan(unbiased_probs)] = 0

    return unbiased_probs

def generate_EdgeProbs_from_Attractiveness(G, coverage_probs, phi, omega=4):
    N=nx.number_of_nodes(G)
    coverage_prob_matrix=torch.zeros((N,N))
    for i, e in enumerate(list(G.edges())):
        #G.edge[e[0]][e[1]]['coverage_prob']=coverage_prob[i]
        coverage_prob_matrix[e[0]][e[1]]=coverage_probs[i]
        coverage_prob_matrix[e[1]][e[0]]=coverage_probs[i] # for undirected graph only

    # GENERATE EDGE PROBABILITIES 
    adj = torch.Tensor(nx.adjacency_matrix(G).toarray())
    adj_phi = adj * phi - omega * coverage_prob_matrix - (1 - adj) * 100 # adding -100 to all the non-adjacent entries
    transition_probs = torch.nn.Softmax(dim=1)(adj_phi)
    transition_probs = transition_probs * adj

    return transition_probs

def prob2unbiased(G, coverage_probs, biased_probs, omega): # no need to be normalized. It will be normalized later
    N=nx.number_of_nodes(G)
    coverage_prob_matrix=torch.zeros((N,N))
    for i, e in enumerate(list(G.edges())):
        coverage_prob_matrix[e[0]][e[1]]=coverage_probs[i]
        coverage_prob_matrix[e[1]][e[0]]=coverage_probs[i] # for undirected graph only

    unbiased_probs = biased_probs * torch.exp(coverage_prob_matrix * omega) # removing the effect of coverage
    unbiased_probs = unbiased_probs / (torch.sum(unbiased_probs, keepdim=True, dim=1) + MEAN_REG)
    unbiased_probs[torch.isnan(unbiased_probs)] = 0

    return unbiased_probs

def marginal_rewards(coverage_probs, G, unbiased_probs, U, initial_distribution, edge_set, omega=4, lib=torch):
    n = len(G.nodes)
    m = len(G.edges)
    edges = G.edges
    targets = list(G.graph["targets"]) + [n] # adding the caught node
    transient_vector = list(set(range(n)) - set(targets))

    # COVERAGE PROBABILITY MATRIX
    coverage_prob_matrix=torch.zeros((n,n))
    edges = list(G.edges())
    for i, edge_idx in enumerate(edge_set):
        e = edges[edge_idx]
        coverage_prob_matrix[e[0]][e[1]]=coverage_probs[i]
        coverage_prob_matrix[e[1]][e[0]]=coverage_probs[i] # for undirected graph only

    adj = torch.Tensor(nx.adjacency_matrix(G).toarray())
    exponential_term = torch.exp(- omega * coverage_prob_matrix) * unbiased_probs * adj
    marginal_prob = exponential_term / (torch.sum(exponential_term, keepdim=True, dim=1) + MEAN_REG)
    marginal_prob[torch.isnan(marginal_prob)] = 0

    state_prob = marginal_prob * (1 - coverage_prob_matrix)
    # ============================== # TODO
    node2edge_prob = torch.zeros((n,m))
    for edge_idx in range(m):
        e = edges[edge_idx]
        node2edge_prob[e[0], edge_idx] = state_prob[e[0]][e[1]]
        node2edge_prob[e[1], edge_idx] = state_prob[e[1]][e[0]]
    # ==============================
    caught_prob = 1 - torch.sum(state_prob, keepdim=True, dim=1)
    full_prob = torch.cat((state_prob, caught_prob), dim=1)

    Q = full_prob[transient_vector][:,transient_vector]
    N = (torch.eye(Q.shape[0]) * (1 + REG) - Q).inverse()
    Nj = torch.sum(N, dim=0)

    edge_used_prob = torch.mm(Nj, node2edge_prob)

    return

def get_optimal_coverage_prob(G, unbiased_probs, U, initial_distribution, budget, omega=4, options={}, method='SLSQP', initial_coverage_prob=None, tol=0.1, edge_set=None):
    """
    Inputs: 
        G is the graph object with dictionaries G[node], G[graph] etc. 
        phi is the attractiveness function, for each of the N nodes, phi(v, Fv)
    """
    N=nx.number_of_nodes(G)
    E=nx.number_of_edges(G)

    if edge_set is None:
        edge_set = set(range(E))

    # Randomly initialize coverage probability distribution
    if initial_coverage_prob is None:
        initial_coverage_prob=np.random.rand(len(edge_set))
        initial_coverage_prob=budget*(initial_coverage_prob/np.sum(initial_coverage_prob))
        # initial_coverage_prob = np.zeros(len(edge_set))
    
    # Bounds and constraints
    bounds=[(0.0,1.0) for _ in edge_set]

    eq_fn = lambda x: budget - sum(x)
    constraints=[{'type': 'eq','fun': eq_fn, 'jac': autograd.jacobian(eq_fn)}]
    
    # Optimization step
    coverage_prob_optimal= minimize(objective_function_matrix_form,initial_coverage_prob,args=(G, unbiased_probs, torch.Tensor(U), torch.Tensor(initial_distribution), edge_set, omega, np), method=method, jac=dobj_dx_matrix_form, bounds=bounds, constraints=constraints, tol=tol, options=options)
    
    return coverage_prob_optimal

def get_optimal_coverage_prob_frank_wolfe(G, unbiased_probs, U, initial_distribution, budget, omega=4, num_iterations=100, initial_coverage_prob=None, tol=0.1, edge_set=None):
    N=nx.number_of_nodes(G)
    E=nx.number_of_edges(G)

    if edge_set is None:
        edge_set = set(range(E))

    # Randomly initialize coverage probability distribution
    if initial_coverage_prob is None:
        initial_coverage_prob = np.zeros(len(edge_set))

    x = initial_coverage_prob
    for k in range(num_iterations):
        gamma = 2 / (k + 2)
        dx = dobj_dx_matrix_form(x, G, unbiased_probs, torch.Tensor(U), torch.Tensor(initial_distribution), edge_set, omega, np)

        model = Model()
        model.setParam('OutputFlag', False)
        coverage_prob = [model.addVar(lb=0.0, ub=1.0) for j in range(len(edge_set))]
        model.addConstr(sum(coverage_prob) <= budget)
        model.setObjective(np.dot(dx, coverage_prob))
        model.optimize()

        # print(model.ObjVal)
        s = np.array([var.x for var in coverage_prob])
        x = x + gamma * (s - x)
    
    return x

def objective_function_matrix_form(coverage_probs, G, unbiased_probs, U, initial_distribution, edge_set, omega=4, lib=torch, approximate=False):
    n = len(G.nodes)
    targets = list(G.graph["targets"]) + [n] # adding the caught node
    transient_vector = list(set(range(n)) - set(targets))

    # COVERAGE PROBABILITY MATRIX
    coverage_prob_matrix=torch.zeros((n,n))
    edges = list(G.edges())
    for i, edge_idx in enumerate(edge_set):
        e = edges[edge_idx]
        coverage_prob_matrix[e[0]][e[1]]=coverage_probs[i]
        coverage_prob_matrix[e[1]][e[0]]=coverage_probs[i] # for undirected graph only

    adj = torch.Tensor(nx.adjacency_matrix(G).toarray())
    exponential_term = torch.exp(- omega * coverage_prob_matrix) * unbiased_probs * adj
    marginal_prob = exponential_term / (torch.sum(exponential_term, keepdim=True, dim=1) + MEAN_REG)
    marginal_prob[torch.isnan(marginal_prob)] = 0

    state_prob = marginal_prob * (1 - coverage_prob_matrix)
    caught_prob = 1 - torch.sum(state_prob, keepdim=True, dim=1)
    full_prob = torch.cat((state_prob, caught_prob), dim=1)

    Q = full_prob[transient_vector][:,transient_vector]
    R = full_prob[transient_vector][:,targets]

    # Q = full_prob[transient_vector[:-1].type(torch.bool)][:,transient_vector.type(torch.bool)]
    # R = full_prob[transient_vector[:-1].type(torch.bool)][:,(1 - transient_vector).type(torch.bool)]
    if approximate:
        N = torch.eye(Q.shape[0]) + Q
    else:
        N = (torch.eye(Q.shape[0]) * (1 + REG) - Q).inverse()
    B = N @ R
    obj = torch.Tensor(initial_distribution) @ B @ torch.Tensor(U)

    if lib == np:
        obj = obj.detach().numpy()

    return obj

def objective_function_matrix_form_np(coverage_probs, G, unbiased_probs, U, initial_distribution, edge_set, omega=4, approximate=False):
    n = len(G.nodes)
    targets = list(G.graph["targets"]) + [n] # adding the caught node
    transient_vector = list(set(range(n)) - set(targets))

    # COVERAGE PROBABILITY MATRIX
    coverage_prob_matrix = np.zeros((n,n))
    edges = list(G.edges())
    for i, edge_idx in enumerate(edge_set):
        e = edges[edge_idx]
        coverage_prob_matrix[e[0]][e[1]]=coverage_probs[i]
        coverage_prob_matrix[e[1]][e[0]]=coverage_probs[i] # for undirected graph only

    adj = np.array(nx.adjacency_matrix(G).toarray())
    exponential_term = np.exp(- omega * coverage_prob_matrix) * unbiased_probs * adj
    marginal_prob = exponential_term / (np.sum(exponential_term, keepdims=True, axis=1) + MEAN_REG)
    marginal_prob[np.isnan(marginal_prob)] = 0

    state_prob = marginal_prob * (1 - coverage_prob_matrix)
    caught_prob = 1 - np.sum(state_prob, keepdims=True, axis=1)
    full_prob = np.concatenate((state_prob, caught_prob), axis=1)

    Q = full_prob[transient_vector][:,transient_vector]
    R = full_prob[transient_vector][:,targets]

    if approximate:
        N = np.eye(Q.shape[0]) + Q
    else:
        N = np.linalg.inv((np.eye(Q.shape[0]) * (1 + REG) - Q))
    B = N @ R
    obj = (initial_distribution @ B) @ U

    return obj

def dobj_dx_matrix_form(coverage_probs, G, unbiased_probs, U, initial_distribution, edge_set, omega=4, lib=torch, approximate=False):
    n = len(G.nodes)
    targets = list(G.graph["targets"]) + [n] # adding the caught node
    transient_vector = list(set(range(n)) - set(targets))

    # COVERAGE PROBABILITY MATRIX
    coverage_prob_matrix=torch.zeros((n,n))
    edges = list(G.edges())
    for i, edge_idx in enumerate(edge_set):
        e = edges[edge_idx]
        coverage_prob_matrix[e[0]][e[1]]=coverage_probs[i]
        coverage_prob_matrix[e[1]][e[0]]=coverage_probs[i] # for undirected graph only

    adj = torch.Tensor(nx.adjacency_matrix(G).toarray())
    exponential_term = torch.exp(- omega * coverage_prob_matrix) * unbiased_probs * adj
    marginal_prob = exponential_term / (torch.sum(exponential_term, keepdim=True, dim=1) + MEAN_REG)
    marginal_prob[torch.isnan(marginal_prob)] = 0

    state_prob = marginal_prob * (1 - coverage_prob_matrix)
    caught_prob = torch.sum(marginal_prob * coverage_prob_matrix, keepdim=True, dim=1)
    full_prob = torch.cat((state_prob, caught_prob), dim=1)

    Q = full_prob[transient_vector][:,transient_vector]
    R = full_prob[transient_vector][:,targets]

    N = (torch.eye(Q.shape[0]) * (1 + REG) - Q).inverse()
    B = N @ R

    dstate_dx = torch.zeros((n,n,len(coverage_probs)))

    edges = list(G.edges())
    # =============== newer implementation of gradient computation ================ # speed up like 6 sec per instance
    for j, edge_j_idx in enumerate(edge_set):
        edge_j = edges[edge_j_idx]
        (v, w) = edge_j
        for u in G.neighbors(v): # case: v->u and v->w
            dstate_dx[v,u,j] = omega * (1 - coverage_prob_matrix[v,u]) * marginal_prob[v,w]
        dstate_dx[v,w,j] = dstate_dx[v,w,j] - omega * (1 - coverage_prob_matrix[v,w]) - 1

        for u in G.neighbors(w): # case: w->u and w->v
            dstate_dx[w,u,j] = omega * (1 - coverage_prob_matrix[w,u]) * marginal_prob[w,v]
        dstate_dx[w,v,j] = dstate_dx[w,v,j] - omega * (1 - coverage_prob_matrix[w,v]) - 1

    dstate_dx = torch.einsum('ij,ijk->ijk', marginal_prob, dstate_dx)

    dcaught_dx = -torch.sum(dstate_dx, keepdim=True, dim=1)
    dfull_dx = torch.cat((dstate_dx, dcaught_dx), dim=1)
    dQ_dx = dfull_dx[transient_vector][:,transient_vector,:]
    dR_dx = dfull_dx[transient_vector][:,targets,:]

    if approximate:
        distdQ_dx = torch.einsum("a,abc", initial_distribution, dQ_dx)
        RU = R @ U
        distdQ_dxRU = torch.einsum("bc,b", distdQ_dx, RU)
        dIQ = initial_distribution + initial_distribution @ Q
        dR_dxU = torch.einsum("abc,b", dR_dx, U)
        dIQ_dR_dxU = torch.einsum("a,ac", dIQ, dR_dxU)
        dobj_dx = distdQ_dxRU + dIQ_dR_dxU
    else:
        distN = initial_distribution @ N
        distNdQ_dxNRU = distN @ torch.einsum("abc,b->ac", dQ_dx, (N @ (R @ U)))
        distNdR_dxU = distN @ (torch.einsum("abc,b->ac", dR_dx, U))
        dobj_dx = distNdQ_dxNRU + distNdR_dxU
        # print('gradient time:', time.time() - start_time)

    if lib == np:
        dobj_dx = dobj_dx.detach().numpy()

    return dobj_dx

# numpy version of the first derivative
def dobj_dx_matrix_form_np(coverage_probs, G, unbiased_probs, U, initial_distribution, edge_set, omega=4, approximate=False):
    n = len(G.nodes)
    targets = list(G.graph["targets"]) + [n] # adding the caught node
    transient_vector = list(set(range(n)) - set(targets))

    # COVERAGE PROBABILITY MATRIX
    coverage_prob_matrix = np.zeros((n,n))
    edges = list(G.edges())
    for i, edge_idx in enumerate(edge_set):
        e = edges[edge_idx]
        coverage_prob_matrix[e[0]][e[1]]=coverage_probs[i]
        coverage_prob_matrix[e[1]][e[0]]=coverage_probs[i] # for undirected graph only

    adj = np.array(nx.adjacency_matrix(G).toarray())
    exponential_term = np.exp(- omega * coverage_prob_matrix) * unbiased_probs * adj
    marginal_prob = exponential_term / (np.sum(exponential_term, keepdims=True, axis=1) + MEAN_REG)
    marginal_prob[np.isnan(marginal_prob)] = 0

    state_prob = marginal_prob * (1 - coverage_prob_matrix)
    caught_prob = np.sum(marginal_prob * coverage_prob_matrix, keepdims=True, axis=1)
    full_prob = np.concatenate((state_prob, caught_prob), axis=1)

    Q = full_prob[transient_vector][:,transient_vector]
    R = full_prob[transient_vector][:,targets]

    N = np.linalg.inv((np.eye(Q.shape[0]) * (1 + REG) - Q))
    B = N @ R

    dstate_dx = np.zeros((n,n,len(coverage_probs)))

    edges = list(G.edges())
    # =============== newer implementation of gradient computation ================ # speed up like 6 sec per instance
    for j, edge_j_idx in enumerate(edge_set):
        edge_j = edges[edge_j_idx]
        (v, w) = edge_j
        for u in G.neighbors(v): # case: v->u and v->w
            dstate_dx[v,u,j] = omega * (1 - coverage_prob_matrix[v,u]) * marginal_prob[v,w]
        dstate_dx[v,w,j] = dstate_dx[v,w,j] - omega * (1 - coverage_prob_matrix[v,w]) - 1

        for u in G.neighbors(w): # case: w->u and w->v
            dstate_dx[w,u,j] = omega * (1 - coverage_prob_matrix[w,u]) * marginal_prob[w,v]
        dstate_dx[w,v,j] = dstate_dx[w,v,j] - omega * (1 - coverage_prob_matrix[w,v]) - 1

    dstate_dx = np.einsum('ij,ijk->ijk', marginal_prob, dstate_dx)

    dcaught_dx = -np.sum(dstate_dx, keepdims=True, axis=1)
    dfull_dx = np.concatenate((dstate_dx, dcaught_dx), axis=1)
    dQ_dx = dfull_dx[transient_vector][:,transient_vector,:]
    dR_dx = dfull_dx[transient_vector][:,targets,:]

    if approximate:
        distdQ_dx = np.einsum("a,abc", initial_distribution, dQ_dx)
        RU = R @ U
        distdQ_dxRU = np.einsum("bc,b", distdQ_dx, RU)
        dIQ = initial_distribution + initial_distribution @ Q
        dR_dxU = np.einsum("abc,b", dR_dx, U)
        dIQ_dR_dxU = np.einsum("a,ac", dIQ, dR_dxU)
        dobj_dx = distdQ_dxRU + dIQ_dR_dxU
    else:
        distN = initial_distribution @ N
        distNdQ_dxNRU = distN @ np.einsum("abc,b->ac", dQ_dx, (N @ (R @ U)))
        distNdR_dxU = distN @ (np.einsum("abc,b->ac", dR_dx, U))
        dobj_dx = distNdQ_dxNRU + distNdR_dxU
        # print('gradient time:', time.time() - start_time)

    return dobj_dx

def obj_hessian_matrix_form(coverage_probs, G, unbiased_probs, U, initial_distribution, edge_set, omega=4, lib=torch, approximate=False):
    if type(coverage_probs) == torch.Tensor:
        coverage_probs = coverage_probs.detach()
    else:
        coverage_probs = torch.Tensor(coverage_probs)

    x = torch.autograd.Variable(coverage_probs, requires_grad=True)
    dobj_dx = dobj_dx_matrix_form(torch.Tensor(x), G, unbiased_probs, U, initial_distribution, edge_set, omega=omega, lib=torch, approximate=approximate)
    m = len(x)
    obj_hessian = torch.zeros((m,m))
    for i in range(len(x)):
        obj_hessian[i] = torch.autograd.grad(dobj_dx[i], x, create_graph=False, retain_graph=True)[0]

    return obj_hessian

def obj_hessian_matrix_form_np(coverage_probs, G, unbiased_probs, U, initial_distribution, edge_set, omega=4, lib=torch, approximate=False):
    g = lambda x: dobj_dx_matrix_form_np(x, G, unbiased_probs, U, initial_distribution, edge_set, omega=omega, approximate=approximate)
    obj_hessian = autograd.jacobian(g)(coverage_probs)
    return obj_hessian

if __name__=='__main__':
    
    # CODE BLOCK FOR GENERATING G, U, INITIAL_DISTRIBUTION, BUDGET
    G=returnGraph(fixed_graph=True)
    E=nx.number_of_edges(G)
    N=nx.number_of_nodes(G)
    nodes=list(G.nodes())
    sources=list(G.graph['sources'])
    targets=list(G.graph['targets'])
    transients=[node for node in nodes if not (node in G.graph['targets'])]
    initial_distribution=np.array([1.0/len(sources) if n in sources else 0.0 for n in transients])
    
    U=[G.node[t]['utility'] for t in targets]
    U.append(-20)
    print ('U:', U)
    U=np.array(U)
    budget=0.5*E
    
    
    # CODE BLOCK FOR GENERATING PHI (GROUND TRUTH PHI GENERATED FOR NOW)
    node_feature_size=25
    net1= GCNDataGenerationNet(node_feature_size)     
    # Define node features for each of the n nodes
    for node in list(G.nodes()):
        node_features=np.random.randn(node_feature_size)
        G.node[node]['node_features']=node_features
    Fv=np.zeros((N,node_feature_size))
    for node in list(G.nodes()):
        Fv[node]=G.node[node]['node_features']
    Fv_torch=torch.as_tensor(Fv, dtype=torch.float)
    # Generate attractiveness values for nodes
    A=nx.to_numpy_matrix(G)
    A_torch=torch.as_tensor(A, dtype=torch.float) 
    phi=(net1.forward(Fv_torch,A_torch).view(-1)).detach()
    unbiased_probs = phi2prob(G, phi)
    

    optimal_coverage_probs=get_optimal_coverage_prob(G, unbiased_probs, U, initial_distribution, budget)
    print ("Optimal coverage:\n", optimal_coverage_probs)
    print("Budget: ", budget)
    print ("Sum of coverage probabilities: ", sum(optimal_coverage_probs['x']))
