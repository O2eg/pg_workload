SET search_path = imdb;

SELECT
    t.title,
    t.production_year,
    cn.name AS company,
    n.name AS performer,
    k.keyword,
    mi.info AS budget
FROM title AS t
JOIN movie_companies AS mc ON mc.movie_id = t.id
JOIN company_name AS cn ON cn.id = mc.company_id
JOIN cast_info AS ci ON ci.movie_id = t.id AND ci.nr_order <= 3
JOIN name AS n ON n.id = ci.person_id
JOIN movie_keyword AS mk ON mk.movie_id = t.id
JOIN keyword AS k ON k.id = mk.keyword_id
JOIN movie_info AS mi ON mi.movie_id = t.id
JOIN info_type AS it ON it.id = mi.info_type_id AND it.info = 'budget'
WHERE t.production_year BETWEEN 2010 AND 2022
  AND cn.country_code IN ('[us]', '[de]', '[jp]', '[pl]')
ORDER BY t.production_year DESC, t.title
LIMIT 200;
