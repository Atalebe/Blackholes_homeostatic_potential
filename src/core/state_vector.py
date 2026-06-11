def compute_phi_bh(df, h_hat_col="H_hat", s_hat_col="S_hat",
                   m_hat_col=None, r_hat_col=None):
    phi = df[h_hat_col] + df[s_hat_col]
    if m_hat_col is not None:
        phi = phi + df[m_hat_col]
    if r_hat_col is not None:
        phi = phi + df[r_hat_col]
    df["phi_bh"] = phi
    return df
