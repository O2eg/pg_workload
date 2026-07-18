SET search_path = imdb;

SELECT
    t.title,
    t.production_year,
    c.name AS company,
    p.name AS performer,
    k.keyword,
    mi.info
FROM title t
JOIN movie_company mc ON mc.title_id = t.id
JOIN company c ON c.id = mc.company_id
JOIN cast_info ci ON ci.title_id = t.id AND ci.billing_order <= 3
JOIN person p ON p.id = ci.person_id
JOIN movie_keyword mk ON mk.title_id = t.id
JOIN keyword k ON k.id = mk.keyword_id
JOIN movie_info mi ON mi.title_id = t.id AND mi.info_type = 'budget'
WHERE t.production_year BETWEEN 2010 AND 2022
  AND c.country_code IN ('US', 'GB', 'DE', 'FR')
  AND t.votes > 10000
ORDER BY t.rating DESC, t.votes DESC
LIMIT 200;
