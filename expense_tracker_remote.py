from fastmcp import FastMCP
import os
import aiosqlite  
import tempfile
from datetime import datetime, timedelta
import dateutil.parser
import calendar

def normalize_date(date_str):
    dt = dateutil.parser.parse(date_str)
    return dt.strftime("%Y-%m-%d")

TEMP_DIR = tempfile.gettempdir()
DB_PATH = os.path.join(TEMP_DIR, "expenses.db")
BUDGET_PATH = os.path.join(TEMP_DIR, "budgets.db")
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

print(f"Database path: {DB_PATH}")

mcp = FastMCP("ExpenseTracker")

def init_db():
    try:
        import sqlite3
        with sqlite3.connect(DB_PATH) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""
                CREATE TABLE IF NOT EXISTS expenses(
                    expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT DEFAULT '',
                    note TEXT DEFAULT ''
                )
            """)

            c.execute("INSERT OR IGNORE INTO expenses(date, amount, category) VALUES ('2000-01-01', 0, 'test')")
            c.execute("DELETE FROM expenses WHERE category = 'test'")
            print("Database initialized successfully with write access")
            c.execute("DELETE FROM sqlite_sequence WHERE name='expenses'")

    except Exception as e:
        print(f"Database initialization error: {e}")
        raise

def init_budget_db(): 
    try:
        import sqlite3
        with sqlite3.connect(BUDGET_PATH) as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("""
                CREATE TABLE IF NOT EXISTS budgets(
                    category TEXT PRIMARY KEY,
                    monthly_limit REAL NOT NULL
                )
            """)
    
            c.execute("INSERT OR IGNORE INTO budgets(category, monthly_limit) VALUES ('test', 0)")
            c.execute("DELETE FROM budgets WHERE category = 'test'")
            print("Database initialized successfully with write access")
    except Exception as e:
        print(f"Database initialization error: {e}")
        raise

init_db()
init_budget_db()

@mcp.tool()
async def add_expense(date, amount, category, subcategory="", note=""):  
    '''Add a new expense entry to the database.'''
    try:
        date = normalize_date(date)
        async with aiosqlite.connect(DB_PATH) as c: 
            cur = await c.execute(  
                "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (?,?,?,?,?)",
                (date, amount, category, subcategory, note)
            )
            expense_id = cur.lastrowid
            await c.commit()  
            return {"status": "success", "expense_id": expense_id, "message": "Expense added successfully"}
    except Exception as e:  
        if "readonly" in str(e).lower():
            return {"status": "error", "message": "Database is in read-only mode. Check file permissions."}
        return {"status": "error", "message": f"Database error: {str(e)}"}
    
@mcp.tool()
async def list_expenses(
    start_date=None,
    end_date=None,
    category=None,
    min_amount=None,
    max_amount=None,
    note_contains=None,
    limit=None
):
    """List expense entries with flexible filtering."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:

            query = """
                SELECT expense_id, date, amount, category, subcategory, note
                FROM expenses
            """

            conditions = []
            params = []

            # Date filters
            if start_date:
                start_date = normalize_date(start_date)
                conditions.append("date >= ?")
                params.append(start_date)

            if end_date:
                end_date = normalize_date(end_date)
                conditions.append("date <= ?")
                params.append(end_date)

            # Category filter
            if category:
                conditions.append("LOWER(category) = LOWER(?)")
                params.append(category)

            # Amount filters
            if min_amount is not None:
                conditions.append("amount >= ?")
                params.append(min_amount)

            if max_amount is not None:
                conditions.append("amount <= ?")
                params.append(max_amount)

            # Note search
            if note_contains:
                conditions.append("LOWER(note) LIKE LOWER(?)")
                params.append(f"%{note_contains}%")

            # Apply WHERE clause
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Sorting
            query += " ORDER BY date DESC, expense_id DESC"

            # Limit
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)

            cur = await c.execute(query, params)

            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    except Exception as e:
        return {"status": "error", "message": f"Error listing expenses: {str(e)}"}

@mcp.tool()
async def summarize(start_date, end_date, category=None): 
    '''Summarize expenses by category within an inclusive date range.'''
    start_date = normalize_date(start_date)
    end_date = normalize_date(end_date)
    try:
        async with aiosqlite.connect(DB_PATH) as c:  
            query = """
                SELECT category, SUM(amount) AS total_amount, COUNT(*) as count
                FROM expenses
                WHERE date BETWEEN ? AND ?
            """
            params = [start_date, end_date]

            if category:
                query += " AND category = ?"
                params.append(category)

            query += " GROUP BY category ORDER BY total_amount DESC"

            cur = await c.execute(query, params) 
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]
    except Exception as e:
        return {"status": "error", "message": f"Error summarizing expenses: {str(e)}"}
    
@mcp.tool()
async def delete_expenses(start_date=None, end_date=None, category=None):
    '''Delete expenses filtered by date range and/or category.'''
    try:
        async with aiosqlite.connect(DB_PATH) as c: 
            query = """
                DELETE FROM expenses
                """
            params = []
            conditions = []
            
            if start_date:
                start_date = normalize_date(start_date)
                conditions.append("date >= ?")
                params.append(start_date)

            if end_date:
                end_date = normalize_date(end_date)
                conditions.append("date <= ?")
                params.append(end_date)

            if category:
                conditions.append("category = ?")
                params.append(category)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)


            cur = await c.execute(query, params)
            await c.commit()
            deleted_count = cur.rowcount

            return {
                "status": "success",
                "deleted_rows": deleted_count,
                "message": f"{deleted_count} expense(s) deleted"
                }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error deleting expenses: {str(e)}"
            }
    
@mcp.tool()
async def delete_expense_by_id(expense_id: int):
    """Delete a specific expense using its ID."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            cur = await c.execute(
                "DELETE FROM expenses WHERE expense_id = ?",
                (expense_id,)
            )

            await c.commit()

            if cur.rowcount == 0:
                return {
                    "status": "error",
                    "message": f"No expense found with id {expense_id}"
                }

            return {
                "status": "success",
                "deleted_expense_id": expense_id,
                "message": f"Expense {expense_id} deleted successfully"
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error deleting expense: {str(e)}"
        }
    
@mcp.tool()
async def update_expense(expense_id: int, date=None, amount=None, category=None, subcategory=None, note=None):
    """Update fields of an existing expense."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            updates = []
            params = []

            if date:
                date = normalize_date(date)
                updates.append("date = ?")
                params.append(date)

            if amount is not None:
                updates.append("amount = ?")
                params.append(amount)

            if category:
                updates.append("category = ?")
                params.append(category)

            if subcategory is not None:
                updates.append("subcategory = ?")
                params.append(subcategory)

            if note is not None:
                updates.append("note = ?")
                params.append(note)

            if not updates:
                return {
                    "status": "error",
                    "message": "No fields provided to update"
                }

            query = f"UPDATE expenses SET {', '.join(updates)} WHERE expense_id = ?"
            params.append(expense_id)

            cur = await c.execute(query, params)
            await c.commit()

            if cur.rowcount == 0:
                return {
                    "status": "error",
                    "message": f"No expense found with id {expense_id}"
                }

            return {
                "status": "success",
                "updated_expense_id": expense_id,
                "message": "Expense updated successfully"
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error updating expense: {str(e)}"
        }
    
@mcp.tool()
async def total_spending(start_date=None, end_date=None):
    """Get total spending in a date range."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:
            query = "SELECT SUM(amount) AS total FROM expenses"
            params = []

            if start_date and end_date:
                start_date = normalize_date(start_date)
                end_date = normalize_date(end_date)
                query += " WHERE date BETWEEN ? AND ?"
                params.extend([start_date, end_date])

            cur = await c.execute(query, params)
            row = await cur.fetchone()

            return {
                "status": "success",
                "total_spending": row[0] if row[0] else 0
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@mcp.tool()
async def recent_expenses(
    limit: int = 5,
    category=None,
    subcategory=None,
    note_contains=None
):
    """Return the most recent expenses with optional filters."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:

            query = """
                SELECT expense_id, date, amount, category, subcategory, note
                FROM expenses
            """

            conditions = []
            params = []

            if category:
                conditions.append("LOWER(category) = LOWER(?)")
                params.append(category)

            if subcategory:
                conditions.append("LOWER(subcategory) = LOWER(?)")
                params.append(subcategory)

            if note_contains:
                conditions.append("LOWER(note) LIKE LOWER(?)")
                params.append(f"%{note_contains}%")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY date DESC, expense_id DESC LIMIT ?"
            params.append(limit)

            cur = await c.execute(query, params)

            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@mcp.tool()
async def spending_insights(start_date=None, end_date=None):
    """Generate simple insights about spending patterns."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:

            conditions = []
            params = []

            if start_date:
                start_date = normalize_date(start_date)
                conditions.append("date >= ?")
                params.append(start_date)

            if end_date:
                end_date = normalize_date(end_date)
                conditions.append("date <= ?")
                params.append(end_date)

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            # Total spending
            cur = await c.execute(
                f"SELECT SUM(amount), COUNT(*) FROM expenses {where_clause}",
                params
            )
            total_spending, total_transactions = await cur.fetchone()

            # Average expense
            cur = await c.execute(
                f"SELECT AVG(amount) FROM expenses {where_clause}",
                params
            )
            avg_expense = (await cur.fetchone())[0] or 0

            # Median expense
            cur = await c.execute(
                f"""SELECT amount 
                FROM expenses {where_clause}
                ORDER BY amount
                LIMIT 1
                OFFSET (
                    SELECT COUNT(*)
                    FROM expenses
                    {where_clause}
                ) / 2
                """,
                params * 2
            )

            median_expense_row = await cur.fetchone()
            median_expense = median_expense_row[0] if median_expense_row else 0

            # Top category
            cur = await c.execute(
                f"""
                SELECT category, SUM(amount) as total
                FROM expenses
                {where_clause}
                GROUP BY category
                ORDER BY total DESC
                LIMIT 1
                """,
                params
            )
            top_category = await cur.fetchone()

            # Most expensive transaction
            cur = await c.execute(
                f"""
                SELECT expense_id, date, amount, category
                FROM expenses
                {where_clause}
                ORDER BY amount DESC
                LIMIT 1
                """,
                params
            )
            largest_expense = await cur.fetchone()

            return {
                "status": "success",
                "total_spending": total_spending or 0,
                "total_transactions": total_transactions,
                "average_expense": avg_expense or 0,
                "median_expense": median_expense,
                "top_category": {
                    "category": top_category[0],
                    "amount": top_category[1]
                } if top_category else None,
                "largest_expense": {
                    "expense_id": largest_expense[0],
                    "date": largest_expense[1],
                    "amount": largest_expense[2],
                    "category": largest_expense[3]
                } if largest_expense else None
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error generating insights: {str(e)}"
        }

@mcp.tool()
async def monthly_spending_trend():
    """Compare spending between the current and previous month."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:

            today = datetime.today()

            # Current month start
            current_start = today.replace(day=1)

            # Previous month end
            prev_end_date = current_start - timedelta(days=1)

            # Previous month start
            prev_start = prev_end_date.replace(day=1)

            current_start_str = current_start.strftime("%Y-%m-%d")
            prev_start_str = prev_start.strftime("%Y-%m-%d")
            prev_end_str = prev_end_date.strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")

            # Current month spending
            cur = await c.execute(
                """
                SELECT SUM(amount), COUNT(*)
                FROM expenses
                WHERE date BETWEEN ? AND ?
                """,
                (current_start_str, today_str)
            )
            current_total, current_count = await cur.fetchone()

            # Previous month spending
            cur = await c.execute(
                """
                SELECT SUM(amount), COUNT(*)
                FROM expenses
                WHERE date BETWEEN ? AND ?
                """,
                (prev_start_str, prev_end_str)
            )
            prev_total, prev_count = await cur.fetchone()

            current_total = current_total or 0
            prev_total = prev_total or 0
            current_count = current_count or 0
            prev_count = prev_count or 0

            difference = current_total - prev_total

            # Percent change logic
            if prev_total == 0:
                percent_change = None
            else:
                percent_change = round((difference / prev_total) * 100, 2)

            # Trend direction
            if difference > 0:
                trend = "increased"
            elif difference < 0:
                trend = "decreased"
            else:
                trend = "no change"

            return {
                "status": "success",
                "current_month": current_start.strftime("%Y-%m"),
                "previous_month": prev_start.strftime("%Y-%m"),
                "current_month_spending": current_total,
                "previous_month_spending": prev_total,
                "difference": difference,
                "percent_change": percent_change,
                "trend": trend,
                "current_transactions": current_count,
                "previous_transactions": prev_count
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error calculating monthly trend: {str(e)}"
        }
    
@mcp.tool()
async def spending_forecast():
    """Predict end-of-month spending based on current spending rate."""
    try:
        async with aiosqlite.connect(DB_PATH) as c:

            today = datetime.today()
            current_start = today.replace(day=1)

            start_str = current_start.strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")

            # Total spending so far this month
            cur = await c.execute(
                """
                SELECT SUM(amount), COUNT(*)
                FROM expenses
                WHERE date BETWEEN ? AND ?
                """,
                (start_str, today_str)
            )

            total_spent, transaction_count = await cur.fetchone()

            total_spent = total_spent or 0
            transaction_count = transaction_count or 0

            # Days elapsed
            days_elapsed = today.day

            # Total days in month
            days_in_month = calendar.monthrange(today.year, today.month)[1]

            # Daily spending rate
            daily_rate = total_spent / days_elapsed if days_elapsed > 0 else 0

            # Forecast total
            projected_total = round(daily_rate * days_in_month, 2)

            return {
                "status": "success",
                "month": today.strftime("%Y-%m"),
                "current_spending": total_spent,
                "transactions_so_far": transaction_count,
                "days_elapsed": days_elapsed,
                "days_in_month": days_in_month,
                "daily_spending_rate": round(daily_rate, 2),
                "projected_monthly_spending": projected_total
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error forecasting spending: {str(e)}"
        }
    
@mcp.tool()
async def set_budget(category, monthly_limit):
    """Set or update a monthly budget for a category."""
    try:
        async with aiosqlite.connect(BUDGET_PATH) as c:
            await c.execute(
                """
                INSERT INTO budgets(category, monthly_limit)
                VALUES (?, ?)
                ON CONFLICT(category) DO UPDATE
                SET monthly_limit = excluded.monthly_limit
                """,
                (category, monthly_limit)
            )

            await c.commit()

            return {
                "status": "success",
                "category": category,
                "monthly_limit": monthly_limit
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@mcp.tool()
async def budget_alerts():
    """Check if spending exceeds budget thresholds."""
    try:
        async with aiosqlite.connect(BUDGET_PATH) as c:

            # Attach expenses database
            await c.execute(f"ATTACH DATABASE '{DB_PATH}' AS exp")

            today = datetime.today()
            month_start = today.replace(day=1).strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")

            cur = await c.execute(
                """
                SELECT b.category, b.monthly_limit,
                       IFNULL(SUM(e.amount),0) as spent
                FROM budgets b
                LEFT JOIN exp.expenses e
                ON b.category = e.category
                AND e.date BETWEEN ? AND ?
                GROUP BY b.category
                """,
                (month_start, today_str)
            )

            alerts = []

            rows = await cur.fetchall()

            for category, limit_value, spent in rows:

                usage = spent / limit_value if limit_value > 0 else 0
                percent_used = round(usage * 100, 2)

                if usage >= 1:
                    status = "over_budget"
                elif usage >= 0.8:
                    status = "warning"
                else:
                    status = "ok"

                alerts.append({
                    "category": category,
                    "spent": spent,
                    "budget": limit_value,
                    "percent_used": percent_used,
                    "status": status
                })

            return {
                "status": "success",
                "alerts": alerts
            }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
    
@mcp.tool()
async def financial_health_score():
    """Compute a financial health score (0-100) based on spending habits."""
    try:
        async with aiosqlite.connect(BUDGET_PATH) as db:

            await db.execute(f"ATTACH DATABASE '{DB_PATH}' AS exp")

            today = datetime.today()

            current_start = today.replace(day=1)
            prev_end = current_start - timedelta(days=1)
            prev_start = prev_end.replace(day=1)

            current_start_str = current_start.strftime("%Y-%m-%d")
            prev_start_str = prev_start.strftime("%Y-%m-%d")
            prev_end_str = prev_end.strftime("%Y-%m-%d")
            today_str = today.strftime("%Y-%m-%d")

            # Current month spending
            cur = await db.execute(
                """
                SELECT SUM(amount)
                FROM exp.expenses
                WHERE date BETWEEN ? AND ?
                """,
                (current_start_str, today_str)
            )
            current_spending = (await cur.fetchone())[0] or 0

            # Previous month spending
            cur = await db.execute(
                """
                SELECT SUM(amount)
                FROM exp.expenses
                WHERE date BETWEEN ? AND ?
                """,
                (prev_start_str, prev_end_str)
            )
            prev_spending = (await cur.fetchone())[0] or 0

            budget_score = 100
            warnings = []

            # -----------------------
            # Budget adherence check
            # -----------------------
            cur = await db.execute(
                """
                SELECT b.category, b.monthly_limit,
                       IFNULL(SUM(e.amount),0)
                FROM budgets b
                LEFT JOIN exp.expenses e
                ON b.category = e.category
                AND e.date BETWEEN ? AND ?
                GROUP BY b.category
                """,
                (current_start_str, today_str)
            )

            budget_rows = await cur.fetchall()

            for category, limit_value, spent in budget_rows:

                if limit_value == 0:
                    continue

                usage = spent / limit_value

                if usage > 1:
                    budget_score -= 20
                    warnings.append(f"{category} budget exceeded")
                elif usage > 0.8:
                    budget_score -= 10
                    warnings.append(f"{category} budget close to limit")

            # -----------------------
            # Spending volatility
            # -----------------------
            if prev_spending > 0:
                change = (current_spending - prev_spending) / prev_spending

                if change > 0.5:
                    budget_score -= 20
                    warnings.append("Spending increased sharply vs last month")
                elif change > 0.3:
                    budget_score -= 10
                    warnings.append("Spending increased noticeably vs last month")

            score = max(0, min(100, budget_score))

            # Rating
            if score >= 80:
                rating = "excellent"
            elif score >= 60:
                rating = "good"
            elif score >= 40:
                rating = "fair"
            else:
                rating = "poor"

            return {
                "status": "success",
                "financial_health_score": score,
                "rating": rating,
                "current_month_spending": current_spending,
                "previous_month_spending": prev_spending,
                "warnings": warnings
            }

    except Exception as e:
        return {
            "status": "error",
            "message": f"Error computing financial health score: {str(e)}"
        }

@mcp.resource("expense:///categories", mime_type="application/json")  # Changed: expense:// → expense:///
def categories():
    try:
        # Provide default categories if file doesn't exist
        default_categories = {
            "categories": [
                "Food & Dining",
                "Transportation",
                "Shopping",
                "Entertainment",
                "Bills & Utilities",
                "Healthcare",
                "Travel",
                "Education",
                "Business",
                "Other"
            ]
        }
        
        try:
            with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            import json
            return json.dumps(default_categories, indent=2)
    except Exception as e:
        return f'{{"error": "Could not load categories: {str(e)}"}}'

# Start the server
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
    # mcp.run()
