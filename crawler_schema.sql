drop table if exists ips;
create table ips (
  time_period text not null,
  ip text not null,
  PRIMARY KEY (time_period, ip)
);

drop table if exists nodeCounts;
create table nodeCounts (
    time_period text not null,
    nodes integer not null,
    country text not null,
    PRIMARY KEY (time_period, country)
);

drop table if exists miscStats;
create table miscStats (
  name text not null primary key,
  value integer not null
);
