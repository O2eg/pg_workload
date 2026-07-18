SET search_path = imdb;

SELECT
    p.name,
    k.keyword,
    count(DISTINCT t.id) AS title_count,
    round(avg(t.rating), 2) AS avg_rating
FROM keyword k
JOIN movie_keyword mk ON mk.keyword_id = k.id
JOIN title t ON t.id = mk.title_id
JOIN cast_info ci ON ci.title_id = t.id
JOIN person p ON p.id = ci.person_id
WHERE k.id BETWEEN 1 AND 500
  AND t.votes > 1000
GROUP BY p.id, p.name, k.id, k.keyword
HAVING count(DISTINCT t.id) >= 2
ORDER BY title_count DESC, avg_rating DESC
LIMIT 100;
