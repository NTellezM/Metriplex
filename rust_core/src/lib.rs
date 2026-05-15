use pyo3::prelude::*;

const SCALE_FACTOR: i64 = 1 << 30; // 2^30

#[inline(always)]
fn fp_mul(a: i64, b: i64) -> i64 {
    (a * b) / SCALE_FACTOR
}

/// chaos_game — muestreo del atractor IFS en ℝ⁴
/// Equivalente exacto a crypto/keys.py::chaos_game()
#[pyfunction]
fn chaos_game(
    matrices: Vec<Vec<Vec<i64>>>,
    vectores: Vec<Vec<i64>>,
    iterations: usize,
    burn_in: usize,
) -> PyResult<Vec<Vec<i64>>> {
    let k = matrices.len();
    let d = matrices[0].len();
    let total = iterations + burn_in;

    // Escalar a f64 igual que Python
    let sf = SCALE_FACTOR as f64;
    let m: Vec<Vec<Vec<f64>>> = matrices.iter()
        .map(|mat| mat.iter()
            .map(|row| row.iter().map(|&v| v as f64 / sf).collect())
            .collect())
        .collect();
    let v: Vec<Vec<f64>> = vectores.iter()
        .map(|vec| vec.iter().map(|&val| val as f64 / sf).collect())
        .collect();

    // PRNG determinista — xorshift64 con semilla fija
    let mut rng_state: u64 = 0xdeadbeefcafe1337;
    let mut next_idx = || -> usize {
        rng_state ^= rng_state << 13;
        rng_state ^= rng_state >> 7;
        rng_state ^= rng_state << 17;
        (rng_state as usize) % k
    };

    let mut x = vec![0.0f64; d];
    let mut attractor: Vec<Vec<i64>> = Vec::with_capacity(iterations);

    for step in 0..total {
        let idx = next_idx();
        let mut xnew = vec![0.0f64; d];
        for r in 0..d {
            let mut acc = v[idx][r];
            for c in 0..d {
                acc += m[idx][r][c] * x[c];
            }
            xnew[r] = acc;
        }
        x = xnew;
        if step >= burn_in {
            attractor.push(x.iter().map(|&val| (val * sf) as i64).collect());
        }
    }

    Ok(attractor)
}

/// calculate_m3_tensor — tensor de tercer orden M₃ en ℝ⁴
/// Equivalente exacto a crypto/tensors.py::calculate_m3_tensor()
#[pyfunction]
fn calculate_m3_tensor(x_points: Vec<Vec<i64>>) -> PyResult<Vec<Vec<Vec<i64>>>> {
    let n = x_points.len();
    let d = 4usize;
    let n_fp = (n as i64) * SCALE_FACTOR;

    // Centroide
    let mut mu = [0i64; 4];
    for p in &x_points {
        for k in 0..d {
            mu[k] += p[k];
        }
    }
    for k in 0..d {
        mu[k] = (mu[k] * SCALE_FACTOR) / n_fp;
    }

    // Tensor M3 — triple producto centrado
    let mut m3 = [[[0i64; 4]; 4]; 4];

    for p in &x_points {
        let mut xc = [0i64; 4];
        for k in 0..d {
            xc[k] = p[k] - mu[k];
        }
        for i in 0..d {
            for j in 0..d {
                let ij = fp_mul(xc[i], xc[j]);
                for k in 0..d {
                    m3[i][j][k] += fp_mul(ij, xc[k]);
                }
            }
        }
    }

    // Promediar por N
    let result: Vec<Vec<Vec<i64>>> = (0..d).map(|i| {
        (0..d).map(|j| {
            (0..d).map(|k| {
                (m3[i][j][k] * SCALE_FACTOR) / n_fp
            }).collect()
        }).collect()
    }).collect();

    Ok(result)
}

#[pymodule]
fn metriplex_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(chaos_game, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_m3_tensor, m)?)?;
    Ok(())
}
