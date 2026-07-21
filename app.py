import streamlit as st
import pandas as pd
import numpy as np
import requests
import pytz
from datetime import datetime, date


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MLB K Prop Engine v11.1",
    page_icon="⚾",
    layout="wide",
)


# ── Data loading helpers ──────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_board():
    """Load the main projection board from CSV data."""
    try:
        df = pd.read_csv("learning_data/graded_history_MASTER_FINAL.csv")
        return df
    except Exception as e:
        st.error(f"Error loading board data: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_dates():
    """Return available game dates from the board."""
    board = load_board()
    if board.empty or "date" not in board.columns:
        return []
    return sorted(board["date"].dropna().unique().tolist(), reverse=True)


# ── Tab render functions ──────────────────────────────────────────────────────

def render_kproj_tab(board: pd.DataFrame):
    st.subheader("⚾ K Projections")
    if board.empty:
        st.warning("No projection data available.")
        return
    st.dataframe(board, use_container_width=True)


def render_pitcher_fs_tab(board: pd.DataFrame):
    st.subheader("🎯 Pitcher Fantasy Scores")
    if board.empty:
        st.warning("No pitcher fantasy score data available.")
        return
    cols = [c for c in board.columns if "fs" in c.lower() or "fantasy" in c.lower()]
    display = board[cols] if cols else board
    st.dataframe(display, use_container_width=True)


def render_moneyline_tab(board: pd.DataFrame):
    st.subheader("💰 Moneyline")
    if board.empty:
        st.warning("No moneyline data available.")
        return
    cols = [c for c in board.columns if "ml" in c.lower() or "moneyline" in c.lower()]
    display = board[cols] if cols else board
    st.dataframe(display, use_container_width=True)


def render_bullpen_tab(board: pd.DataFrame):
    st.subheader("🔥 Bullpen Fatigue")
    try:
        bullpen = pd.read_csv("learning_data/Bullpen.csv")
        st.dataframe(bullpen, use_container_width=True)
    except Exception:
        if board.empty:
            st.warning("No bullpen data available.")
        else:
            st.dataframe(board, use_container_width=True)


def render_team_offense_tab(board: pd.DataFrame):
    st.subheader("🏟️ Team Offense")
    try:
        offense = pd.read_csv("learning_data/TeamOffense.csv")
        st.dataframe(offense, use_container_width=True)
    except Exception:
        if board.empty:
            st.warning("No team offense data available.")
        else:
            st.dataframe(board, use_container_width=True)


def render_grading_tab(board: pd.DataFrame):
    st.subheader("📊 Grading & CLV Tracking")
    if board.empty:
        st.warning("No grading data available.")
        return
    st.dataframe(board, use_container_width=True)


# ── Main entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    board = load_board()
    dates = load_dates()

    st.title("⚾ MLB K Prop Engine v11.1")

    if dates:
        selected_date = st.sidebar.selectbox("Select Date", dates)
        if "date" in board.columns:
            board = board[board["date"] == selected_date]
    else:
        st.sidebar.info("No dates available.")

    (
        tab_kproj,
        tab_pitcher_fs,
        tab_moneyline,
        tab_bullpen,
        tab_team_offense,
        tab_grading,
    ) = st.tabs([
        "K Projections",
        "Pitcher Fantasy Scores",
        "Moneyline",
        "Bullpen Fatigue",
        "Team Offense",
        "Grading & CLV",
    ])

    with tab_kproj:
        render_kproj_tab(board)

    with tab_pitcher_fs:
        render_pitcher_fs_tab(board)

    with tab_moneyline:
        render_moneyline_tab(board)

    with tab_bullpen:
        render_bullpen_tab(board)

    with tab_team_offense:
        render_team_offense_tab(board)

    with tab_grading:
        render_grading_tab(board)
