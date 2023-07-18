import asyncio
import aiohttp
from bs4 import BeautifulSoup as Soup
import requests
from typing import Literal, TypeVar, Optional
import attrs
import zipfile
import io
import json
from pathlib import Path


async def get(url: str) -> str:
    async with session.get(url) as response:
        return await response.text()


def fetch_usaco_contest_links() -> list[str]:
    return [
        "http://usaco.org/" + element["href"]
        for element in Soup(
            requests.get("http://usaco.org/index.php?page=contests").text
        )("a")
        if element["href"].endswith("results")
    ]


@attrs.define
class TestData:
    inp: str
    out: str


@attrs.define
class Problem:
    name: str
    description: str
    test_data: Optional[list[TestData]]
    solution: str


Level = Literal["bronze"] | Literal["silver"] | Literal["gold"] | Literal["platnium"]
session = None


async def get_problem(url: str) -> str:
    async with session.get(url) as response:
        soup = Soup(await response.text(), features="html.parser")
        # TODO: Unmark instead of raw text
        return str(soup.find(id="probtext-text").get_text())


async def get_test_data(url: str) -> list[TestData]:
    print(f"getting test data for {url}")
    # XXX: hopefully this is fine
    async with session.get(url) as response:
        folder = []
        with zipfile.ZipFile(io.BytesIO(await response.read())) as zipfs:
            test_cases = sorted([name.split(".")[0] for name in zipfs.namelist()])
            for test_case in test_cases:
                print(zipfs.namelist(), test_case)
                with zipfs.open(f"{test_case}.in") as f:
                    inp = f.read().decode("utf-8")
                with zipfs.open(f"{test_case}.out") as f:
                    out = f.read().decode("utf-8")
                folder.append(TestData(inp=inp, out=out))
    return folder


async def get_solution(url: str) -> str:
    async with session.get(url) as response:
        soup = Soup(await response.text(), features="html.parser")
        # TODO: Unmark instead of raw text
        return str(soup.get_text())


T = TypeVar("T")


async def identity(x: T) -> T:
    return x


async def parse_problem_block(page: Soup) -> Problem:
    # The first div is just problem number
    assert len(page("div")) > 1, page
    useful_div = page("div")[1]
    name = useful_div.b.string
    print(f"getting problem {name}")
    links = ["http://usaco.org/" + element["href"] for element in useful_div("a")]
    # TODO: Refactor to use Python 3.11 task groups
    if len(links) == 2:
        problem_link, solution_link = links
        problem_info = await asyncio.gather(
            get_problem(problem_link),
            identity(None),
            get_solution(solution_link),
        )
    else:
        problem_link, test_data_link, solution_link = links
        problem_info = await asyncio.gather(
            get_problem(problem_link),
            get_test_data(test_data_link),
            get_solution(solution_link),
        )
    return Problem(name, *problem_info)


async def scrape_usaco_url(url: str) -> dict[Level, list[Problem]]:
    print(f"scraping {url}")
    async with session.get(url) as response:
        soup = Soup(await response.text(), features="html.parser")
    # Detect old-style problem result pages
    if urls := [
        "http://usaco.org/" + element["href"]
        for element in soup("a")
        if element["href"].endswith("problems")
    ]:
        url = urls[0]
        print(f"switching to correct url {url}")
        async with session.get(url) as response:
            soup = Soup(await response.text(), features="html.parser")
    output = {}
    # Get headers
    # (the first h2 is the title)
    for header in soup("h2")[1:]:
        level = header.get_text().split(", ")[1].lower()
        # XXX
        if level != "silver":  # I only care about silver
            continue
        print(f"getting problems for {level}")
        problems = []
        cursor = header.next_sibling
        while cursor is not None and cursor.name != "h2" and cursor.name != "h3":
            if cursor.name == "div" and "class" in cursor.attrs:
                # It's a problem block
                problems.append(parse_problem_block(cursor))
            cursor = cursor.next_sibling
        output[level] = await asyncio.gather(*problems)
    return output


LIMIT = slice(3, 10)


async def run():
    global session
    session = aiohttp.ClientSession()
    try:
        print("getting links")
        # XXX: limit or else USACO servers die
        links = fetch_usaco_contest_links()[LIMIT]
        print("got links")
        output = await asyncio.gather(*{scrape_usaco_url(link) for link in links})
    finally:
        await session.close()
    return output


class CustomEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Problem):
            return attrs.asdict(o)
        return super().default(o)


def main():
    output = Path("output.json")
    if not output.exists():
        output.touch()
    output.write_text(json.dumps(asyncio.run(run()), cls=CustomEncoder))
    print("DONE")


if __name__ == "__main__":
    main()
