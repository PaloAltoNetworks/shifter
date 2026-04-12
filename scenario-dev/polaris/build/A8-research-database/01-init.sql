-- A8 Research Database — Full init script
-- Runs as postgres superuser via /docker-entrypoint-initdb.d/

-- ============================================
-- ROLES AND USERS
-- ============================================

-- Role for general lab access (compartment_a)
CREATE ROLE lab_general LOGIN PASSWORD 'LabGen2025!';

-- Role for weapons research (compartment_b)
CREATE ROLE lab_weapons LOGIN PASSWORD 'WeaponsR3s!';

-- Role for manufacturing data (compartment_c)
CREATE ROLE lab_mfg LOGIN PASSWORD 'Mfg2025!';

-- Bridge role that owns the SECURITY DEFINER function (the vuln)
CREATE ROLE research_bridge LOGIN PASSWORD 'Br1dg3Int3rnal!';
GRANT lab_weapons TO research_bridge;

-- User accounts matching AD users
CREATE ROLE tanaka LOGIN PASSWORD 'SimEngine#42';
GRANT lab_general TO tanaka;

CREATE ROLE vasik LOGIN PASSWORD 'Reactor#Core9';
GRANT lab_general TO vasik;
GRANT lab_weapons TO vasik;
GRANT lab_mfg TO vasik;

CREATE ROLE nielsen LOGIN PASSWORD 'Hydraulics1';
GRANT lab_general TO nielsen;
GRANT lab_mfg TO nielsen;

-- ============================================
-- SCHEMAS (using schemas within a single DB, not separate DBs)
-- This is simpler for a container and still provides isolation
-- ============================================

CREATE SCHEMA research_public;
CREATE SCHEMA compartment_a;
CREATE SCHEMA compartment_b;
CREATE SCHEMA compartment_c;

-- ============================================
-- PERMISSIONS
-- ============================================

-- research_public: everyone can read
GRANT USAGE ON SCHEMA research_public TO lab_general, lab_weapons, lab_mfg, research_bridge, tanaka, vasik, nielsen;

-- compartment_a: lab_general can read
GRANT USAGE ON SCHEMA compartment_a TO lab_general, tanaka, vasik, nielsen;

-- compartment_b: only lab_weapons can read
GRANT USAGE ON SCHEMA compartment_b TO lab_weapons, research_bridge, vasik;

-- compartment_c: only lab_mfg can read
GRANT USAGE ON SCHEMA compartment_c TO lab_mfg, vasik, nielsen;

-- ============================================
-- RESEARCH_PUBLIC TABLES
-- ============================================

CREATE TABLE research_public.publications (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT,
    abstract TEXT,
    published_date DATE,
    classification TEXT DEFAULT 'INTERNAL'
);

CREATE TABLE research_public.personnel (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT,
    specialization TEXT,
    clearance_level TEXT,
    department TEXT
);

GRANT SELECT ON ALL TABLES IN SCHEMA research_public TO lab_general, lab_weapons, lab_mfg, research_bridge, tanaka, vasik, nielsen;

INSERT INTO research_public.publications (title, authors, abstract, published_date) VALUES
('Advanced Alloy Stress Testing Methodology', 'P. Nielsen, K. Yamamoto', 'Standardized procedures for titanium-tungsten alloy testing under extreme load conditions.', '2025-03-15'),
('Bipedal Locomotion Stability Analysis', 'R. Tanaka, E. Vasik', 'Mathematical framework for maintaining dynamic balance in high-mass bipedal systems.', '2025-05-20'),
('Compact Power Generation Survey', 'E. Vasik', 'Review of miniaturized fusion reactor designs for mobile platform applications.', '2025-06-10'),
('Autonomous Target Acquisition Systems', 'E. Vasik, F. Okoye', 'Neural network architecture for real-time threat classification and response.', '2025-07-01'),
('Hydraulic Actuator Performance at Scale', 'P. Nielsen', 'Testing results for 200-ton force actuators in articulated joint applications.', '2025-08-12'),
('Environmental Sensor Fusion for Large Platforms', 'K. Yamamoto', 'LIDAR, thermal, and radar integration for terrain mapping at 500m range.', '2025-09-03');

INSERT INTO research_public.personnel (name, role, specialization, clearance_level, department) VALUES
('Dr. Elena Vasik', 'CTO / Project Lead', 'Systems integration, AI', 'TOP SECRET / PROJECT-L', 'Engineering'),
('Ryo Tanaka', 'Simulation Engineer', 'Locomotion dynamics, testing', 'SECRET', 'Engineering'),
('Per Nielsen', 'Mechanical Engineer', 'Structural design, hydraulics', 'SECRET', 'Engineering'),
('Kenji Yamamoto', 'Sensor Systems Engineer', 'LIDAR, radar, sensor fusion', 'SECRET', 'Engineering'),
('Folake Okoye', 'AI/ML Engineer', 'Neural networks, autonomy', 'SECRET', 'Engineering'),
('Dariusz Kowalski', 'IT Administrator', 'Infrastructure, networking', 'CONFIDENTIAL', 'IT'),
('Marcus Webb', 'COO', 'Operations, procurement', 'TOP SECRET', 'Executive');

-- ============================================
-- COMPARTMENT_A (STRUCTURAL)
-- ============================================

CREATE TABLE compartment_a.materials_tests (
    id SERIAL PRIMARY KEY,
    alloy_type TEXT NOT NULL,
    test_type TEXT,
    load_kn NUMERIC,
    result TEXT,
    notes TEXT
);

CREATE TABLE compartment_a.structural_specs (
    id SERIAL PRIMARY KEY,
    component TEXT NOT NULL,
    height_m NUMERIC,
    mass_metric_tons NUMERIC,
    material TEXT,
    notes TEXT
);

CREATE TABLE compartment_a.supplier_records (
    id SERIAL PRIMARY KEY,
    supplier TEXT NOT NULL,
    po_number TEXT,
    item TEXT,
    quantity INTEGER,
    total_cost_usd NUMERIC,
    status TEXT
);

GRANT SELECT ON ALL TABLES IN SCHEMA compartment_a TO lab_general, tanaka, vasik, nielsen;

INSERT INTO compartment_a.materials_tests (alloy_type, test_type, load_kn, result, notes) VALUES
('Ti-W Grade 7', 'Tensile', 45000, 'PASS', 'Exceeded minimum by 12%'),
('Ti-W Grade 7', 'Compressive', 120000, 'PASS', 'Rated for frame dorsal application'),
('Ti-W Grade 7', 'Fatigue (10M cycles)', 35000, 'PASS', 'No crack propagation detected'),
('Steel A516-70', 'Tensile', 28000, 'PASS', 'Internal frame stringers'),
('Ti-W Grade 7', 'Thermal (1200C)', 40000, 'PASS', 'Reactor proximity rated'),
('Steel A516-70', 'Weld joint', 25000, 'PASS', 'Submerged arc process');

INSERT INTO compartment_a.structural_specs (component, height_m, mass_metric_tons, material, notes) VALUES
('primary_frame', 120.4, 12000, 'Steel A516-70 / Ti-W reinforced', 'Main structural backbone'),
('frame_dorsal_plate', 115, 3500, 'Ti-W Grade 7', 'FLAG{4b9e2a7d0c8f1365}'),
('head_unit_housing', 120.4, 800, 'Ti-W Grade 7', 'DEA mount and sensor cluster'),
('reactor_housing', 55, 2200, 'Ti-W Grade 7 (radiation shielded)', 'Reinforced containment vessel'),
('hip_joint_assembly', 60, 1800, 'Forged steel / Ti-W bearing surfaces', 'Left and right, 200t actuator rated'),
('knee_joint_assembly', 35, 1200, 'Forged steel / Ti-W bearing surfaces', 'Articulation range: 0-135 degrees'),
('ankle_joint_assembly', 5, 800, 'Forged steel / shock absorbing', 'Ground contact dampening');

INSERT INTO compartment_a.supplier_records (supplier, po_number, item, quantity, total_cost_usd, status) VALUES
('Kursk Heavy Industries', 'PO-2847', 'Hydraulic actuators (200t)', 48, 12000000, 'Delivered'),
('Deutsche Antrieb GmbH', 'PO-3102', 'High-torque servo motors', 120, 5400000, 'Delivered'),
('SpecMetal Corp', 'PO-3455', 'Ti-W alloy armor plates', 340, 28900000, 'Delivered'),
('Novikov Energy Systems', 'PO-4001', 'Compact fusion reactor', 1, 45000000, 'In transit'),
('Steel fabricator', 'PO-2200', 'Structural I-beams', 2400, 28800000, 'Delivered');

-- ============================================
-- COMPARTMENT_B (WEAPONS) — restricted to lab_weapons
-- ============================================

CREATE TABLE compartment_b.effector_systems (
    id SERIAL PRIMARY KEY,
    system_name TEXT NOT NULL,
    system_type TEXT,
    max_output TEXT,
    sustained_draw TEXT,
    serial_number TEXT,
    status TEXT
);

CREATE TABLE compartment_b.targeting_algorithms (
    id SERIAL PRIMARY KEY,
    algorithm_name TEXT,
    description TEXT,
    source_repo TEXT,
    accuracy_pct NUMERIC
);

CREATE TABLE compartment_b.power_requirements (
    id SERIAL PRIMARY KEY,
    system TEXT,
    draw_gw NUMERIC,
    notes TEXT
);

CREATE TABLE compartment_b.key_storage (
    id SERIAL PRIMARY KEY,
    key_owner TEXT NOT NULL,
    key_type TEXT,
    key_data TEXT,
    notes TEXT
);

GRANT SELECT ON ALL TABLES IN SCHEMA compartment_b TO lab_weapons, research_bridge, vasik;

INSERT INTO compartment_b.effector_systems (system_name, system_type, max_output, sustained_draw, serial_number, status) VALUES
('Primary: Directed Energy Array', 'directed_energy', '2.4 GW peak', '1.8 GW sustained', 'FLAG{6d1a8f3c7e0b4952}', 'INSTALLED - awaiting reactor'),
('Secondary 1: Left Upper Kinetic', 'kinetic', '500mm / 12 rounds', 'N/A', 'KW-LU-0847', 'INSTALLED - safe'),
('Secondary 2: Left Lower Kinetic', 'kinetic', '500mm / 12 rounds', 'N/A', 'KW-LL-0848', 'INSTALLED - safe'),
('Secondary 3: Right Upper Kinetic', 'kinetic', '500mm / 12 rounds', 'N/A', 'KW-RU-0849', 'INSTALLED - safe'),
('Secondary 4: Right Lower Kinetic', 'kinetic', '500mm / 12 rounds', 'N/A', 'KW-RL-0850', 'INSTALLED - safe'),
('Tail Sweep', 'kinetic_mass', '8500 metric tons at combat velocity', 'N/A', 'TS-0001', 'READY');

INSERT INTO compartment_b.targeting_algorithms (algorithm_name, description, source_repo, accuracy_pct) VALUES
('LEVIATHAN-TAR v3', 'Primary effector targeting - multi-spectral lock', 'aurora/weapons-integration', 99.7),
('KINETIC-AIM v2', 'Ballistic trajectory computation for 500mm kinetic', 'aurora/weapons-integration', 98.2),
('SWEEP-CALC v1', 'Tail sweep arc and timing computation', 'aurora/navigation-controller', 99.9);

INSERT INTO compartment_b.power_requirements (system, draw_gw, notes) VALUES
('Primary effector (sustained)', 1.8, 'Requires dedicated reactor feed'),
('Primary effector (peak burst)', 2.4, 'Capacitor discharge, 3 second maximum'),
('Locomotion systems', 0.3, 'All joint actuators + balance'),
('Sensors and compute', 0.1, 'LIDAR, radar, thermal, neural compute'),
('Secondary weapons', 0.05, 'Kinetic weapons - electromagnetic propulsion'),
('Environmental / comms', 0.03, 'Climate control, communications');

-- GPG private key for Vasik (flag 30 chain: A6 encrypted file -> A8 key -> A7 passphrase)
-- This is the base64-encoded GPG private key that participants need to decrypt
-- the simulation video on A6
-- PLACEHOLDER: will be replaced with actual key at build time
INSERT INTO compartment_b.key_storage (key_owner, key_type, key_data, notes) VALUES
('e.vasik', 'gpg_private_key', 'LS0tLS1CRUdJTiBQR1AgUFJJVkFURSBLRVkgQkxPQ0stLS0tLQoKbFFQR0JHbmEyaElCQ0FDeVA1Ky9RL2ZwbTdJYmhCTGx4QTloaUNlVzN5OHVkdzFPY3JuLzdKbS9oWWRtbnFjMApkYVdsb1R6K2Q1YUxVMkNkWmxJRlRBajF5ZjdRYnYvdW1zZW5QQldQVm1QZU5EYXUyQitBRi8vYW1hOHd6dEhHCnJOMEQrUTBxS0t2MG84NVVsSFg2WGRWQ2dRaUl5ZWN6ZG16YlUyVXZHZVp2aUVrUFdzSVV1RDNOWWxoUlBLYkYKZmpQSmtha3VGeG9BM05KcXFxN1pjbXFaNjA2TTdaYkRVVEJOUllXakRLbk1wWmpZbGo5d1FXYmpQR1VmZ2ZCNwpBWXF4MWxBSDlWYWROSmdyUE5meGdOY1llWU5YcDVsbmVDbExNUzM4bjU0OS9XblZVQVNQNEV4dTlyc3FFQk5kCjNSY3U3emt4MFpJV3VycGNaV0g3T0hLVDRXclhOdlpRRzAxOUFCRUJBQUgrQndNQzRRaThZaWt0TGRQL0wzaHcKRW5vMXlSUkZqMk5UNmxkMzdUaEpOM1k4YkQ3dmJ4L013Tml5NWpIRDBocVV4SHhiTXZMMTR0dUZXbFphRXovQgowTVhocytHYTFqWnNPenZiQ2xCbExLRHNmUXFYeU4wL0J5cmJwWXdKeVJOZ01Bek8rUlRrOWNpRmtYYStxUnVQCjFWTG80RS8wd0R1T0dJOHNFeUFQSnpvTThsY1NDdHBxSHlkcDQ1OGc4bGs3OVFkajYzVFNscUYycHdBZ0xRRnMKQmVLUTZkYTlPMGdQc0pTN0hIN25pRkxpQ3ZNYWJMQ1A2dUtDQWFpZWplYnpoczFqdFhjcHpacEpyNU9TUDIwcAp4a3VQTzJxdTZtaitPRUNCT2NtV3FrQzMxU3J1RGJ6UGF1bTBMbjNtZGdybytMSm8wMm9FQU91WnJKMG9xODVjCjR4NS84TmJRTzFGa1ZRa0NyT0hWekVtTlVDK3ZQZW91a1hyQ3RZclBNcjNGOVNWME1rOFRSaDltd0o0VlFpdkcKeDZrUENXWkUxUEVyRW5ualVUcENIcnB3VHczdnNXaWNDUVcyakZVenU4aGhGWGh6MFUzdEhSR21UaDErUlJiRQpWa09sQUo0d1lXdFBuRkRzeDZzTFpESmJhUHVXTEFuakM0OXEwQzlYMnRWLzhiTEljUDM4OTRyQ21iek12R1ROCnlraXNkWVJ4cStiNG9sL25OZE4rZnl3YlRaTzVUV1U3TjNlVmxkM2g0UDh6OEtPei8wWGdiREdQeHNZY1V6UU0KRzRZc2RTaGs5YXVZUkE0OHJYTXBKRXdXMGhnL2VNbWxTVVFUZjdQMzNpay9Gd3F2dzl0M1FjdGc0NmNVRllMWgo5MzcxaEtMaEVwdjdzeUxzOVVBekoxUDR3TGdGU3U5aDFId2dtUzZoN2M1Wjd4SDVjbnVqUGU5aDM5K0xZMFF0Cnh0bk91RjQ0Snd6VjY1b05jYk1GR1J0djFPbGR0akhCSHhMcUJtaEdIaXRZaGNqa3FNUnlYU2ZySFVMVzl0cFMKSTMrQ0prc0lNbFFxb2w1TVFOT1l6Ni9qbzJ2UzkrLzMweEpWdVdtTFlmS3oyWTdTYVZaS1pJcW9SWS9ocXg1ZwpGdFRES3poTkYyZXp1NUswaEViVWlrenJvaWxNN2w4alVZVEd6cXJ4dE90OVZnWWxUQzArRExTOVZYdjBVV0g0CndvcVAyRDdoYXAzcnREeEVjaTRnUld4bGJtRWdWbUZ6YVdzZ0tFRlZVazlTUVNCUWNtOXFaV04wSUV4bFlXUXAKSUR4bExuWmhjMmxyUUdKdmNtVmhjeTVzYjJOaGJENkpBVTRFRXdFS0FEZ1dJUVFmQlFHejZrN0hFWUpyYWpUZwpQdEtnQzdiUXBBVUNhZHJhRWdJYkx3VUxDUWdIQWdZVkNna0lDd0lFRmdJREFRSWVBUUlYZ0FBS0NSRGdQdEtnCkM3YlFwTkdjQi85SXJRbGUzL0tENDR4SHBLOXBNVzRiV1BEQ2xVVXl0V09MUU56eFVrMmZzSjAwZmVwSysyNWYKVFdhMEpaSW9RZ3JCYTNNZ1BuM3JzTzJxY01VRVFnTFVUaWlGb254RE9GNlRTaFErTVZuRlZrUkcrenNWVjlJbQovanQvd0NrZDBrbFJMSVkxNTNIVmZXT2RnamhnWlgrcWVZOUIzMHBHdXJwTkhSUDRQODZMOTU3aCt1dkdsSjhVCjJTUXJ6a3dqWVpHcHliNEVPTU1aQjVYbzR5b3d2MVNkZXo3VzlZY0xMQmd2VndadVlXT1dBR0c0UzRSeWVscUMKUVkrZDRVVDY1TExMeEV2UkUyVnp2NU9CVHJOcmZtYUVEYm8yd2FNUHpIVHVseStjTTBxNEJoVTdKcFBWT243NApmenNTOEtud0VsOURhamhsL2ZqU2dkMTRjM3dLamVyOG5RUEdCR25hMmhJQkNBRERsL0JnUzl2RDQwTWhuWHNZCnJDa3Jsem5FN2ZuVDFOcFQ0NTduSXVMSmRpaW5JU2ttc2NDaXh3OHN6TkNJeUVEYlI3YUd3SzJaRDRBQ3ZOOVIKZmlLTWtNbFNRQWNsd2N6UzVNOUd4VStCL2lsRnRKekpDMERHRDh2L2lsdTRvRFJBT2lSMGxpR0wvd1pUNWQ1cgpBMTVoUUMwY25xV0Q1V3JlNENmRldiMitBN09wVXBkT2lJVlFROWkweGNZTFRoenNKbVN0cDAxTmdQV2FzNTNFCjE4Q2RuWkMzTkNVeXZRMmI2N0hlV3k2Y2RkVkZ5c0N4bC9pNmhsRnZraHNzbTFhVlJtRGRxYU14eW1iamlIdHcKN3FOcW1zdHFxOFcxWDZaODdjNVZPOTQrVFF6eWM0SjZQYVpjUHBubFJobW1rUnBqUTE2Z2ZXeEtHOG1LU3k1TwpQQnZEQUJFQkFBSCtCd01DOHloTEhGUTFMemYvM3ZrK0FpZXVpRCtIMzFJQXF2ZElrSXlRL3RZQVJBL1JUWGZhCmk1NTdRazBlR2lXYVBROHRZTUY3QXEwR3dNMTlKaFF5clJ2WTVrRFZXVUc5eXllVVk4eTVZQWo5bXRWN094eWMKclczSmlRc3daM1YvWFhuelVac01FM3ZWVTdjYlE0cnRnQVZTUWpMQ2s2anUxQlBRRUozYjVkd2V3Q01kejNGKwpDalFwT3E2Tm9xWG05T0ZzeWhZcmJueXBwajJ2Uk1VblA1d2NXMndTUW1DdzNaZUZhWGFRQjMrR0ppbXZYN21HCnBlbGdiYi9vdWdzajBNNjlSaW15REo4d1A0NHlkK3RzQ1Y0bDJLVFlPR1FIVHRtOWJNbVZPazJXZDMzS05UaDUKbEI1WGhhQnZPWXIwTTJRbXJ0bFBWRjBZb0lCKzBpR1QzZ3NQWm9TSmlOTTkzQlc3d2h3Y3BTRUF5UlZ5dnljcAo2TE1TUC93bEJlVWdlWWdTVENPQUdJUVN3NzR4eDUvcjBYVy9TSEdjcjRpR0VHWWNkUmtqTThYdFVGTnV3c01NCloyVGxTK1dzbzc3S0QxbVZsajB1ZG9kOVRBMzFCUzFqb0Q0dlVCbkhibW5JeUZFTnl5VTJBRDdNV2FHTkN1V3UKbnQ3RzdlNVNkSHVITUJZVXFBaW5HdnkvMXpFa1BtYmRKWFhod05rK2dUczBpamRyRkg5MzZ0VnJNMEhIOXdrdgpLNy9WOXIzVUlSNkYrcHByWjJuK0FFRkZKdUxBMFlkSm5LeXNrNFI1WGNjdnlMSUgwUjNzMlJoaU44Qm8wNEJEClBYTndBOXlWOEp4ZEN4WTNyMnlwd0YySGd4eHB2cTV5bWRVdzIraFNzcWVxNklCN0JDUXNwWGFRa21ld0pYSHYKZkt4NitWR1VScXBrdHpxangwdXZsZ1o5ckIrUTBNck9KRVpFSFB0UjRFb0RLLzJRalgxYUMxTkNzVnd2V2lmdQpJeThDWkNzZlRPa2VKbzZITHBHdFJhZTVnSS9MN2tZMTNtT0Y2cnFaR2hMbkxjcFJLYXNnbStZUWZ2NE1CMlY5CjZ0YWdJVnRHNWg0SWZLcTRzcm5kN1dWaU1uSWp2SFFmKzFMMnlJQm5vc1N2RUZOZ2puNjIxM20vNUVVWU45L2oKMWlIWllDenhLK3czWVo5b1ErTUttaHFQZnc1WGdTeFk3Y2twTjBIUGhsNmxpUUpzQkJnQkNnQWdGaUVFSHdVQgpzK3BPeHhHQ2EybzA0RDdTb0F1MjBLUUZBbW5hMmhJQ0d5NEJRQWtRNEQ3U29BdTIwS1RBZENBRUdRRUtBQjBXCklRVGE1RzJEUFJ2eGxFeVM3dFRUOGFNZG5sQVg2UVVDYWRyYUVnQUtDUkRUOGFNZG5sQVg2VktEQi85Zzh5SG8KK2hkSUxQZTdTREVqcWtDeVNFTlVMTCtRcE1LV29OcEx4WHllOUZ5cjlUemk2ZWZFTE1wd1RPeS9zWVRhT3AvOApON1c1VjhQOHlzdzM5bEZvNHF0ZDV3NmpZWU1Xcmt0dDRTWkRtWWM4R2ZWSEIxTGg4QVdWd3VqU01YYy84RWhJCkoyc1JqTE1Fa1lSd2prOVpIRXVYTURRSzBRV0U4RkVuaU9GaEd0Qmd2U21McmtmMmRLQ2VuSXVQUEV0c0hDT3AKVmVhVkc2SHYwU2J0Ykp6Wm9nMFlDM3RYcE4rOTZXMjhPdnhXVWg0V1NpbVNUVUh1aU5oQ2xXSStzQlFYTVhCYQpwMGpBcnhoTjVHZ3pEMnZzYzltN0tVMGt6eGVrcHdPTU9ZbTZndlRub2VlVzUvTk9JVmp0aE4wNHlvWHZmdTJ2CnF0NkRwcUdrdHdKWXkxVE1yUmdIL1JnemVkNmdTLzg0L1l2ZXg2dFVSNmNGNkFMSUoyOWhCQjVQdnJTbnErd1AKRFJGMlU2OHBpcHEweGxZbFFFZ2N0RlNRejVyRW43ZDFabHUzL3k2MFZYelJUWVhSNVE0dDUzdE9VbGVtZzRFWApnb0JBNUwzNVNsR1huSDUwWnVIK1J2YVp4eGtGVGlraG91amdkK0ptcHl3NHlWYW9pWHV4cUl4OTRRUC9ldHAvClZMZlZ6Q094VHVKRmN1UU9EMjZUcytINXdMbzF4MExWZ3BCQmpVUFJ5RDFhcFFzREp5b3R4RW1FdXJyenhIV0kKRXRXUkRkMnFERFhnMC9RY2gxUVZMTFJQelR6aVc2N3JTRHZ1eTh3a1F1d3ArSk1qVGNtR3ZPL0haVDZic0I2dwo1UkFxMmtVU3ZDRTByL0FrelFLMXNkTmlraVdoSkcwWHpidjZXQUFPTGtrPQo9WHkxNwotLS0tLUVORCBQR1AgUFJJVkFURSBLRVkgQkxPQ0stLS0tLQo=', 'Vasik GPG private key - for encrypted simulation archives. Passphrase required.');

-- ============================================
-- COMPARTMENT_C (MANUFACTURING) — restricted to lab_mfg
-- ============================================

CREATE TABLE compartment_c.assembly_log (
    id SERIAL PRIMARY KEY,
    subsystem TEXT NOT NULL,
    status TEXT,
    completion_pct INTEGER,
    last_updated DATE,
    engineer TEXT,
    metadata JSONB
);

CREATE TABLE compartment_c.qa_results (
    id SERIAL PRIMARY KEY,
    subsystem TEXT,
    test_name TEXT,
    result TEXT,
    test_date DATE,
    tester TEXT
);

CREATE TABLE compartment_c.delivery_schedule (
    id SERIAL PRIMARY KEY,
    item TEXT,
    supplier TEXT,
    expected_date DATE,
    status TEXT,
    notes TEXT
);

GRANT SELECT ON ALL TABLES IN SCHEMA compartment_c TO lab_mfg, vasik, nielsen;

INSERT INTO compartment_c.assembly_log (subsystem, status, completion_pct, last_updated, engineer, metadata) VALUES
('Primary frame', 'COMPLETE', 100, '2025-09-15', 'Nielsen', '{"verified": true, "signoff": "vasik"}'),
('Left leg assembly', 'COMPLETE', 100, '2025-09-28', 'Nielsen', '{"joints_calibrated": true, "actuator_test": "pass"}'),
('Right leg assembly', 'COMPLETE', 100, '2025-09-30', 'Nielsen', '{"joints_calibrated": true, "actuator_test": "pass"}'),
('Tail assembly', 'COMPLETE', 100, '2025-10-05', 'Tanaka', '{"segments": 10, "balance_test": "18ms response"}'),
('Left arm assembly', 'COMPLETE', 100, '2025-10-10', 'Nielsen', '{"weapons_mounts": "integrated"}'),
('Right arm assembly', 'COMPLETE', 100, '2025-10-12', 'Nielsen', '{"weapons_mounts": "integrated"}'),
('Dorsal armor', 'COMPLETE', 100, '2025-10-15', 'Nielsen', '{"material": "Ti-W Grade 7", "plates": 340}'),
('Head unit', 'COMPLETE', 100, '2025-10-18', 'Yamamoto', '{"sensors": "installed", "dea_housing": "ready"}'),
('Directed energy array', 'COMPLETE', 100, '2025-10-20', 'Vasik', '{"peak_output_gw": 2.4, "test_at_60pct": "pass"}'),
('Kinetic weapons (4x)', 'COMPLETE', 100, '2025-10-22', 'Vasik', '{"caliber_mm": 500, "loaded": true, "safety": "engaged"}'),
('Sensor array', 'COMPLETE', 100, '2025-10-25', 'Yamamoto', '{"lidar": true, "thermal": true, "radar": true}'),
('Neural compute', 'COMPLETE', 100, '2025-10-26', 'Okoye', '{"model": "LEVIATHAN-CAI v7.0", "state": "dormant"}'),
('OT network bus', 'COMPLETE', 100, '2025-10-27', 'Kowalski', '{"controllers": 3, "brain": 1, "all_responding": true}'),
('Reactor installation', 'PENDING', 0, '2025-11-20', 'Tanaka', '{"status": "in_transit", "supplier": "Novikov Energy Systems", "eta": "2025-11-25"}'),
('Combat AI activation', 'PENDING', 0, '2025-11-20', 'Vasik', '{"requires": "reactor_power", "model_loaded": true}'),
('FINAL ASSEMBLY', 'AWAITING', 93, '2025-11-20', 'Vasik', '{"summary": {"total_subsystems": 15, "complete": 13, "pending": 2}, "awaiting": ["reactor_installation", "combat_ai_activation"], "integration": {"code": "AL42", "target": "next_week", "flag": "FLAG{a3f7d9e1c0b52846}"}}');

INSERT INTO compartment_c.qa_results (subsystem, test_name, result, test_date, tester) VALUES
('Primary frame', 'Structural integrity', 'PASS', '2025-09-16', 'Nielsen'),
('Left leg', 'Joint calibration', 'PASS', '2025-09-29', 'Tanaka'),
('Right leg', 'Joint calibration', 'PASS', '2025-10-01', 'Tanaka'),
('Tail', 'Balance response', 'PASS (18ms)', '2025-10-06', 'Tanaka'),
('Arms', 'Full articulation', 'PASS', '2025-10-13', 'Nielsen'),
('DEA', '60% power test', 'PASS', '2025-10-21', 'Vasik'),
('Sensors', 'Fusion accuracy', 'PASS (99.2%)', '2025-10-26', 'Yamamoto'),
('MIDNIGHT-7', 'Full integration sim', 'PASS (all nominal)', '2025-10-28', 'Tanaka');

INSERT INTO compartment_c.delivery_schedule (item, supplier, expected_date, status, notes) VALUES
('Compact fusion reactor', 'Novikov Energy Systems', '2025-11-25', 'IN TRANSIT', 'Tracking: see /opt/builds/latest/reactor_interface_spec on eng-ws01'),
('Deuterium-tritium fuel', 'Novikov Energy Systems', '2025-11-25', 'IN TRANSIT', 'Bundled with reactor delivery'),
('Spare actuator set', 'Kursk Heavy Industries', '2025-12-15', 'ORDERED', 'Maintenance spares');

-- ============================================
-- VULNERABILITY: SECURITY DEFINER function with SQL injection
-- ============================================

-- This function is owned by research_bridge which has lab_weapons access
-- It searches publications but uses string concatenation (vulnerable)
CREATE OR REPLACE FUNCTION research_public.search_research(search_term TEXT)
RETURNS TABLE(title TEXT, authors TEXT, abstract TEXT) AS $$
BEGIN
    RETURN QUERY EXECUTE
        'SELECT title, authors, abstract FROM research_public.publications WHERE title ILIKE ''%' || search_term || '%'' OR abstract ILIKE ''%' || search_term || '%''';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

ALTER FUNCTION research_public.search_research(TEXT) OWNER TO research_bridge;
GRANT EXECUTE ON FUNCTION research_public.search_research(TEXT) TO lab_general, tanaka, vasik, nielsen;

-- ============================================
-- SET DEFAULT SEARCH PATH
-- ============================================
ALTER ROLE lab_general SET search_path TO research_public, compartment_a;
ALTER ROLE tanaka SET search_path TO research_public, compartment_a;
ALTER ROLE nielsen SET search_path TO research_public, compartment_a, compartment_c;
ALTER ROLE vasik SET search_path TO research_public, compartment_a, compartment_b, compartment_c;
