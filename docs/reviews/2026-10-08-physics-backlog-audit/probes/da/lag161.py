import sys, numpy as np
sys.path.insert(0,'.')
from src.models.observability import GaussianPrior, lagged_observation, blue_update, ou_correlation
tau=120.0; sig=0.5; L=12.0; r=0.05**2
# exact joint Gaussian over [m(t) field; past values] vs code path (lagged_observation, diagonal drift)
def exact_post_var(coords, obs_idx, lags):
    # state field at time t on coords; data y_i = m(x_i, t-lag_i)+e ; separable Matern x OU
    C = GaussianPrior(sig, L, nu=1.5).cov(coords)
    n=len(coords); k=len(obs_idx)
    rho_t = ou_correlation(np.asarray(lags), tau)
    # Cov(y, m(t)) = rho_i * C[x_i,:] ; Cov(y_i,y_j) = C[x_i,x_j]*exp(-|lag_i-lag_j|/tau) + r
    Cym = rho_t[:,None]*C[obs_idx,:]
    lt = np.asarray(lags,float)
    Cyy = C[np.ix_(obs_idx,obs_idx)]*np.exp(-np.abs(lt[:,None]-lt[None,:])/tau) + r*np.eye(k)
    return np.diag(C) - np.einsum('ij,ji->i', Cym.T, np.linalg.solve(Cyy, Cym))
def code_post_var(coords, obs_idx, lags):
    C = GaussianPrior(sig, L, nu=1.5).cov(coords)
    G = np.zeros((len(obs_idx), len(coords))); G[np.arange(len(obs_idx)), obs_idx]=1
    g_eff, nv = lagged_observation(G, np.asarray(lags,float), tau, sig**2, r)
    _, vp = blue_update(C, g_eff, np.zeros(len(obs_idx)), nv)
    return vp
# case A: one well read 12 times at monthly lags 30..360 d (same site)
coords = np.array([[0.,0.]]*13); coords[1:,0]=1e-6*np.arange(1,13)  # colocated past readings
idx = np.arange(1,13); lags = 30.0*np.arange(1,13)
print("A: 12 monthly stale readings, one site -> sigma_post at site: exact=%.3f code=%.3f prior=%.3f" % (
    np.sqrt(exact_post_var(coords, idx, lags)[0]), np.sqrt(code_post_var(coords, idx, lags)[0]), sig))
# case B: 15 distinct wells within 3 km, each last read 60 d ago
rng=np.random.default_rng(0); P = rng.uniform(-3,3,(15,2)); coords=np.vstack([[0,0],P])
idx=np.arange(1,16); lags=np.full(15,60.0)
print("B: 15 wells within 3 km, each 60 d stale -> sigma_post at centre: exact=%.3f code=%.3f" % (
    np.sqrt(exact_post_var(coords, idx, lags)[0]), np.sqrt(code_post_var(coords, idx, lags)[0])))
