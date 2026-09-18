-- PostgreSQL reference schema for the generated CSV snapshots.
-- All identities and transactions are synthetic.

CREATE TABLE partners (
    partner_id UUID PRIMARY KEY,
    display_name VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE users (
    user_id UUID PRIMARY KEY,
    display_name VARCHAR(80) NOT NULL,
    home_zone VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE merchants (
    merchant_id UUID PRIMARY KEY,
    partner_id UUID NOT NULL REFERENCES partners(partner_id),
    display_name VARCHAR(100) NOT NULL,
    category VARCHAR(32) NOT NULL,
    zone_code VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE transactions (
    transaction_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id),
    merchant_id UUID NOT NULL REFERENCES merchants(merchant_id),
    amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
    currency CHAR(3) NOT NULL,
    channel VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('pending', 'approved', 'declined', 'refunded')),
    status_version INTEGER NOT NULL CHECK (status_version >= 1),
    created_at TIMESTAMPTZ NOT NULL,
    status_updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX transactions_created_at_idx ON transactions(created_at);
CREATE INDEX transactions_user_created_idx ON transactions(user_id, created_at);
