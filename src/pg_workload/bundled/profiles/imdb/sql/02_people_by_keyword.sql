SET search_path = imdb;

SELECT
    n.name,
    k.keyword,
    count(DISTINCT t.id) AS title_count,
    min(t.production_year) AS first_year,
    max(t.production_year) AS last_year
FROM keyword AS k
JOIN movie_keyword AS mk ON mk.keyword_id = k.id
JOIN title AS t ON t.id = mk.movie_id
JOIN cast_info AS ci ON ci.movie_id = t.id
JOIN name AS n ON n.id = ci.person_id
WHERE k.id BETWEEN 1 AND 500
  AND t.production_year >= 1990
GROUP BY n.id, n.name, k.id, k.keyword
HAVING count(DISTINCT t.id) >= 2
ORDER BY title_count DESC, last_year DESC
LIMIT 100;
