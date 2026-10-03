import argparse
import sys

from .. import config, storage
from ..defaults import DEFAULT_BAR_WIDTH
from . import Command
from .fokus import fokus_run


def read_configure_parser(p: argparse.ArgumentParser) -> None:
    subparsers = p.add_subparsers(dest="read_subcommand", help="read subcommands")
    add_parser = subparsers.add_parser("add", help="Add a new book to read.csv")
    add_parser.add_argument("--title", "-t", required=True, help="Title of the book")
    add_parser.add_argument(
        "--length", "-l", type=int, required=True, help="Total number of pages"
    )
    add_parser.add_argument(
        "--time-per-page", "-P", help="Optional duration per page (e.g. 45s, 2m, 1h30m)"
    )
    update_parser = subparsers.add_parser("update", help="Update reading progress")
    update_parser.add_argument("--title", "-t", required=True, help="Title of the book")
    update_group = update_parser.add_mutually_exclusive_group()
    update_group.add_argument(
        "--plus", "-p", type=int, help="Increment current_page by this amount"
    )
    update_group.add_argument(
        "--at", "-a", type=int, help="Set current_page to this value"
    )
    update_parser.add_argument(
        "--time-per-page", "-P", help="Optional duration per page (e.g. 45s, 2m, 1h30m)"
    )
    p.add_argument("--title", "-t", help="Title of the book to show progress for")


def _format_progress_bar(title: str, length: int, current_page: int) -> str:
    """Format a progress bar for a book. Returns the formatted string."""
    if length == 0:
        return f"{title}: Invalid length (0 pages)"
    percentage = current_page / length * 100 if length > 0 else 0.0
    percentage = min(percentage, 100.0)
    bar_width = int(config.get_config("bar_width", DEFAULT_BAR_WIDTH))
    filled = int(percentage / 100 * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)
    return f"{title}:\n:>{bar} {int(percentage)}% ({current_page}/{length} pages)"


def _show_progress(title: str) -> bool:
    """Show progress bar and ask user if they want to start reading.
    Returns True if user wants to start, False otherwise.
    """
    reads = storage.load_read_csv()
    book = None
    for r in reads:
        if r.get("title") == title:
            book = r
            break
    if not book:
        raise ValueError(f"Book {title!r} not found in read.csv")
    length = book.get("length", 0)
    current_page = book.get("current_page", 0)
    time_per_page_seconds = book.get("time_per_page_seconds", 0)
    print(_format_progress_bar(title, length, current_page))
    estimate_line = _format_estimated_time(length, current_page, time_per_page_seconds)
    if estimate_line:
        print(estimate_line)
    if not sys.stdin.isatty():
        return False
    while True:
        response = input("Start reading? (y/n): ").strip().lower()
        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        else:
            print("Please enter 'y' or 'n'")


def _show_all_progress() -> None:
    """Show progress bars for all books in read.csv."""
    reads = storage.load_read_csv()
    if not reads:
        print("No books in read.csv")
        return
    for book in reads:
        title_obj = book.get("title", "")
        length_obj = book.get("length", 0)
        current_page_obj = book.get("current_page", 0)
        time_per_page_obj = book.get("time_per_page_seconds", 0)
        title = str(title_obj) if title_obj else ""
        length = int(length_obj)
        current_page = int(current_page_obj)
        time_per_page_seconds = int(time_per_page_obj)
        print(_format_progress_bar(title, length, current_page))
        estimate_line = _format_estimated_time(
            length, current_page, time_per_page_seconds
        )
        if estimate_line:
            print(estimate_line)
        print()


def _format_estimated_time(
    length: int, current_page: int, time_per_page_seconds: int
) -> str:
    """Return a formatted estimate to finish if data is available, else ''."""
    try:
        length_int = int(length)
        current_page_int = int(current_page)
        time_per_page_int = int(time_per_page_seconds)
    except (TypeError, ValueError):
        return ""
    if length_int <= 0 or time_per_page_int <= 0:
        return ""
    remaining_pages = max(length_int - current_page_int, 0)
    if remaining_pages == 0:
        return ""
    remaining_seconds = remaining_pages * time_per_page_int
    formatted = storage.format_hms(remaining_seconds)
    return f"Estimated time to finish: {formatted} ({remaining_pages} pages left at {time_per_page_int}s/page)"


def read_run(args: argparse.Namespace) -> int:
    subcommand = getattr(args, "read_subcommand", None)
    if subcommand == "add":
        title = args.title.strip()
        if not title:
            raise ValueError("book title cannot be empty")
        length = args.length
        time_per_page_seconds = 0
        if args.time_per_page:
            try:
                time_per_page_seconds = storage.parse_duration(args.time_per_page)
            except ValueError as e:
                print(f"Error parsing --time-per-page: {e}")
                return 1
        if length <= 0:
            print(f"Error: length must be > 0, got {length}")
            return 1
        reads = storage.load_read_csv()
        for r in reads:
            if r.get("title") == title:
                print(f"Error: Book '{title}' already exists in read.csv")
                return 1
        reads.append(
            {
                "title": title,
                "length": length,
                "current_page": 0,
                "time_per_page_seconds": time_per_page_seconds,
            }
        )
        storage.save_read_csv(reads)
        print(f"Added '{title}' with {length} pages to read.csv")
        return 0
    elif subcommand == "update":
        if args.plus is None and args.at is None and (args.time_per_page is None):
            raise ValueError("provide --plus, --at, or --time-per-page")
        title = args.title.strip()
        time_per_page_seconds = None
        if args.time_per_page:
            try:
                parsed = storage.parse_duration(args.time_per_page)
                time_per_page_seconds = parsed
            except ValueError as e:
                print(f"Error parsing --time-per-page: {e}")
                return 1
        reads = storage.load_read_csv()
        book_index = None
        for i, r in enumerate(reads):
            if r.get("title") == title:
                book_index = i
                break
        if book_index is None:
            print(f"Error: Book '{title}' not found in read.csv")
            return 1
        book = reads[book_index]
        length = book.get("length", 0)
        if args.plus is not None:
            if args.plus < 0:
                print(f"Error: plus must be > 0, got {args.plus}")
                return 1
            current = book.get("current_page", 0)
            new_page = current + args.plus
            if new_page > length:
                raise ValueError("current page cannot exceed book length")
            book["current_page"] = new_page
            print(
                f"Updated '{title}': current_page = {new_page} (incremented by {args.plus})"
            )
        elif args.at is not None:
            if args.at < 0:
                print(f"Error: at must be > 0, got {args.at}")
                return 1
            new_page = args.at
            if new_page > length:
                raise ValueError("current page cannot exceed book length")
            book["current_page"] = new_page
            print(f"Updated '{title}': current_page = {new_page}")
        if time_per_page_seconds is not None:
            book["time_per_page_seconds"] = time_per_page_seconds
            print(
                f"Updated '{title}': time_per_page_seconds = {time_per_page_seconds}s"
            )
        reads[book_index] = book
        storage.save_read_csv(reads)
        return 0
    elif args.title:
        start = _show_progress(args.title)
        if start:
            fokus_args = argparse.Namespace(
                title=args.title,
                comment=None,
                goal=None,
                strict=False,
                context=False,
                online=False,
            )
            return fokus_run(fokus_args)
        return 0
    else:
        _show_all_progress()
        return 0


def get_command() -> Command:
    return Command(
        name="read",
        help="Manage reading list and track reading progress.",
        description="Add books, update reading progress, and view reading statistics.",
        configure_parser=read_configure_parser,
        run=read_run,
        mutates=lambda args: args.read_subcommand in {"add", "update"},
    )
