-- /database/init.sql

-- Create systems table if it doesn't exist
CREATE TABLE IF NOT EXISTS systems (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

-- Create projects table if it doesn't exist
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    system_id INTEGER NOT NULL REFERENCES systems(id)
);

-- Create goods table if it doesn't exist
CREATE TABLE IF NOT EXISTS goods (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

-- Create project_goods table if it doesn't exist
CREATE TABLE IF NOT EXISTS project_goods (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    good_id INTEGER NOT NULL REFERENCES goods(id),
    required INTEGER NOT NULL,
    remaining INTEGER NOT NULL
);

-- Insert sample goods data
INSERT INTO goods (name) VALUES
('Aluminium'),
('Ceramic Composites'),
('CMM Composite'),
('Computer Components'),
('Copper'),
('Food Cartridges'),
('Fruit and Vegetables'),
('Insulating Membrane'),
('Liquid Oxygen'),
('Medical Diagnostic Equipment'),
('Non-Lethal Weapons'),
('Polymers'),
('Power Generators'),
('Semiconductors'),
('Steel'),
('Superconductors'),
('Titanium'),
('Water'),
('Water Purifiers')
ON CONFLICT DO NOTHING;
