SET search_path = imdb;

SELECT
    c.name AS company,
    t.production_year,
    count(DISTINCT t.id) AS titles,
    round(avg(t.rating), 2) AS avg_rating,
    sum(t.votes) AS total_votes
FROM company c
JOIN movie_company mc ON mc.company_id = c.id
JOIN title t ON t.id = mc.title_id
WHERE t.production_year BETWEEN 2000 AND 2022
  AND t.rating >= 6.0
GROUP BY c.id, c.name, t.production_year
ORDER BY total_votes DESC
LIMIT 50;
