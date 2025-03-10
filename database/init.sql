-- Create systems table.
CREATE TABLE IF NOT EXISTS systems (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL
);

-- Create station_requirements table.
CREATE TABLE IF NOT EXISTS station_requirements (
    id SERIAL PRIMARY KEY,
    tier VARCHAR(100) NOT NULL,
    location VARCHAR(100) NOT NULL,
    category VARCHAR(100) NOT NULL,
    listed_type VARCHAR(100) NOT NULL,
    building_type VARCHAR(100) NOT NULL,
    layout VARCHAR(100) NOT NULL,
    commodities JSONB,
    CONSTRAINT uix_station_req UNIQUE (tier, location, category, listed_type, building_type, layout)
);

-- Create projects table with new columns.
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    system_id INTEGER NOT NULL REFERENCES systems(id),
    station_requirement_id INTEGER REFERENCES station_requirements(id),
    requirements JSONB,
    progress JSONB
);
