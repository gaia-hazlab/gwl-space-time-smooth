import sys, numpy as np
sys.path.insert(0, '.')
from src.models.anchor import assimilate_points
from src.models.observability import GaussianPrior, blue_update, matern_correlation
# --- 1. anchor.assimilate_points vs BLUE posterior sigma at a cell 5 km from wells
sig, L, so = 0.5, 12.0, 0.15
for N in (1, 10):
    ox = np.zeros(N); oy = np.zeros(N)
    f, s = assimilate_points(np.array([[5000.]]), np.array([[0.]]), ox, oy, np.ones(N)*0.3, so, L*1000, sig)
    coords = np.vstack([[5.0, 0.0], np.zeros((N, 2))])
    C = GaussianPrior(sig, L, nu=1.5).cov(coords)
    G = np.zeros((N, N+1)); G[np.arange(N), 1+np.arange(N)] = 1
    ma, vp = blue_update(C, G, np.ones(N)*0.3, so**2)
    print(f"N={N} colocated wells @5 km: anchor sigma={float(s.ravel()[0]):.3f} mean={float(f.ravel()[0]):.3f} | BLUE sigma={np.sqrt(vp[0]):.3f} mean={ma[0]:.3f}")
# --- 2. EnKF (stochastic, perturbed obs) on root-zone theta near saturation: bound violations
rng = np.random.default_rng(0)
Ne = 40; th_sat, th_wp = 0.46, 0.12
viol = []; mass = []
for trial in range(2000):
    xf = np.clip(0.43 + 0.03*rng.standard_normal(Ne), th_wp, th_sat)
    y = 0.45; r = 0.03**2
    P = np.var(xf, ddof=1); K = P/(P+r)
    xa = xf + K*(y + np.sqrt(r)*rng.standard_normal(Ne) - xf)
    viol.append(np.mean(xa > th_sat))
    mass.append(np.mean(np.clip(xa, th_wp, th_sat) - xa)*1000)   # mm per 1 m root zone removed by clip
print(f"EnKF theta near saturation: mean fraction of members > theta_sat after update = {np.mean(viol):.3f}; mean clip mass = {np.mean(mass):.2f} mm (1 m root zone) per analysis")
# --- 3. Increment magnitude: 1-sigma head increment in water units
for Sy in (0.30, 0.10, 0.05):
    print(f"Sy={Sy}: 0.5 m head increment = {Sy*0.5*1000:.0f} mm water")
# --- 4. Elastic disk-load vertical displacement at centre (Boussinesq half-space)
nu_p, E = 0.25, 7.5e10
for a_km, h in ((87, 0.10), (87, 0.30), (50, 0.5), (10, 0.3)):
    p = 1000*9.81*h
    uz = 2*(1-nu_p**2)*p*a_km*1e3/E
    print(f"disk radius {a_km} km, {h*1000:.0f} mm water: uz(centre) = {uz*1000:.2f} mm")
# --- 5. sigma ratio: static baseline RMSE vs anomaly prior
print("variance ratio (18.5 m / 0.5 m)^2 =", (18.5/0.5)**2)
# --- 6. Matern decorrelation at 5 km
print("rho(5 km, L=12, nu=1.5) =", float(matern_correlation(5.0, 12.0, 1.5)))
