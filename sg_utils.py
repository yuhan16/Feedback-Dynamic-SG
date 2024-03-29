import numpy as np
import gurobipy as gp
from gurobipy import GRB
import matplotlib.pyplot as plt
#import parameters as pm


class DiscountedStackelbergGame:
    """
    This class defines a dynamic Stackelberg game and functions to computes feedback SG equilibrium.
    """
    def __init__(self) -> None:
        """
        Define game settings. Or load the definition in parameters.py. 
        """
        self.rng = np.random.default_rng(123)  # set seed manually
        self.T = 50         # game horizon
        self.gam = 0.9      # discounted factor
        self.dims, self.dima, self.dimb = 50, 10, 7
        self.ua = 10*self.rng.random((self.dims, self.dima, self.dimb))     # stage cost, ua(s,a,b)
        self.ub = 10*self.rng.random((self.dims, self.dima, self.dimb))
        self.uaf = self.rng.random(self.dims);      # terminal cost
        self.ubf = self.rng.random(self.dims)
        p = self.rng.random((self.dims, self.dims, self.dima, self.dimb))   # p(s'|s,a,b)
        for i in range(self.dims):
            for j in range(self.dima):
                for k in range(self.dimb):
                    p[:, i,j,k] /= p[:, i,j,k].sum()
        self.p = p
        self.bigM = 100

    
    def backward_dp(self):
        """
        This function implements DP to compute the value and the feedback policy.
        va[t,s]: leader's value at time t
        pia[t,s,:]: leader's policy at time t and state s 
        """
        va = np.zeros((self.T+1, self.dims))
        vb = np.zeros((self.T+1, self.dims))
        pia = np.zeros((self.T, self.dims, self.dima))
        pib = np.zeros((self.T, self.dims, self.dimb))

        va[-1, :] = self.uaf    # set terminal value as the terminal cost
        vb[-1, :] = self.ubf
        
        for t in reversed(range(self.T)):
            print('backward DP for stage ', t)
            for s in range(self.dims):
                UA, UB = self.get_compact_cost_matrix(s, va[t+1, :], vb[t+1, :])
                x, y = self.gurobi_MILP(UA, UB)
                #x, y = self.gurobi_MIQP(UA, UB)     # or use MIQP

                # store value and policy
                va[t, :], vb[t, :] = x @ (UA @ y), x @ (UB @ y)
                pia[t,s, :], pib[t,s, :] = x, y
        print("backward DP complete.")
        return va, vb, pia, pib
    

    def get_compact_cost_matrix(self, s, va_tp1, vb_tp1):
        """
        This function formulates compact cost matrices in the bilinear problem.
        UA = ua(s,:) + gam * \sum_{s'}[ p(s'|s,a,b) * va(s')]
        """
        UA = self.ua[s, :] + self.gam * np.tensordot(self.p[:,s,:], va_tp1, axes=(0,0))
        UB = self.ub[s, :] + self.gam * np.tensordot(self.p[:,s,:], vb_tp1, axes=(0,0))
        return UA, UB
        

    def gurobi_MILP(self, UA, UB):
        """
        This function call gurobi to solve the MILP problem.
        Return pia, pib
        """
        try:
            model = gp.Model('sg-milp')
            model.setParam('OutputFlag', 0)
            z = model.addVars(self.dima, self.dimb, lb=0, ub=1, vtype=GRB.CONTINUOUS, name="z")
            y = model.addVar(lb=-GRB.INFINITY, vtype=GRB.CONTINUOUS, name="y")
            x = model.addVars(self.dimb, vtype=GRB.BINARY, name="x")

            model.setObjective(sum(sum(UA[i,j] * z[i,j] for i in range(self.dima)) for j in range(self.dimb)), GRB.MINIMIZE)
            model.addConstr( z.sum() == 1 )
            model.addConstrs( sum(z[i, j] for j in range(self.dimb)) <=1     for i in range(self.dima) )
            model.addConstrs( sum(z[i, j] for i in range(self.dima)) >= x[j] for j in range(self.dimb) )
            model.addConstrs( sum(z[i, j] for i in range(self.dima)) <= 1    for j in range(self.dimb) )
            model.addConstr(x.sum() == 1)
            for j in range(self.dimb):
                model.addConstr( y-sum(UB.T[j, i]*sum(z[i, k] for k in range(self.dimb)) for i in range(self.dima) ) >= 0 )
                model.addConstr( y-sum(UB.T[j, i]*sum(z[i, k] for k in range(self.dimb)) for i in range(self.dima)) <= self.bigM*(1-x[j]) )
            model.optimize()

            # get pia and pib
            ztmp, xtmp = np.zeros((self.dima, self.dimb)), np.zeros(self.dimb)
            for j in range(self.dimb):
                for i in range(self.dimb):
                    ztmp[i, j] = z[i, j].X
                xtmp[j] = x[j].X
            pia, pib = ztmp @ np.ones(self.dimb), xtmp
            return pia, pib

        except gp.GurobiError as e:
            print('Error code ' + str(e.errno) + ": " + str(e))
        except AttributeError:
            print('Encountered an attribute error')

    
    def gurobi_MIQP(self, UA, UB):
        """
        This function calls Gurobi to solve MIQP.
        Return: pia, pib
        """
        try:
            model = gp.Model("sg-miqp")
            model.setParam('OutputFlag', 0)
            a = model.addMVar(shape=1, lb=-GRB.INFINITY, vtype=GRB.CONTINUOUS, name="a")
            y = model.addMVar(shape=self.dima, lb=0, vtype=GRB.CONTINUOUS, name="y")
            x = model.addMVar(shape=self.dimb, vtype=GRB.BINARY, name="x")

            model.setObjective(y @ (UA @ x), GRB.MINIMIZE)

            model.addConstr(y.sum() == 1)
            model.addConstr(x.sum() == 1)
            for j in range(self.dimb):
                model.addConstr( a - UB.T[j, :] @ y >= 0 )
                model.addConstr( a - UB.T[j, :] @ y <= self.bigM*(1-x[j]) )

            model.optimize()

            # compute pia and pib
            pia = y.X
            pib = x.X
            return pia, pib

        except gp.GurobiError as e:
            print('Error code ' + str(e.errno) + ": " + str(e))
        except AttributeError:
            print('Encountered an attribute error')



class PlotUtils:
    def __init__(self) -> None:
        pass


    def plot_value(self, va, vb, s_list):
        """
        This function plots the both player's values of given states s_list.
        va[t,s]: leader's value at time t and state s
        """
        fig, axs = plt.subplots(2)
        fig.suptitle('left leader, right follower')
        for s in s_list:
            axs[0].plot(np.arange(va.shape[0]), va[:, s], label='s='+str(s))
            axs[1].plot(np.arange(va.shape[0]), vb[:, s], label='s='+str(s))
        axs[0].legend()
        axs[1].legend()
        fig.savefig('tmp.png', dpi=300)
        plt.close(fig)


    def plot_policy(pia, pib, T):
        """
        This function plots the policies.
        """