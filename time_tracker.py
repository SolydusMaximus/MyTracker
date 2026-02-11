import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
from datetime import date, timedelta
import calendar
import json
import time

# --- CONFIGURATION ---
st.set_page_config(page_title="MyTracker", layout="wide")

# 🔴 PASTE YOUR GOOGLE SHEET URL HERE 🔴
SHEET_URL = "https://docs.google.com/spreadsheets/d/1zwALYqjWu9rw80e99IcIjwbxRB_SyWp-tFUr_FhtKzs/edit?gid=496663440#gid=496663440"

# --- GLOBAL SCHEMA DEFINITION ---
REQUIRED_TABS = {
    "Users": ["id", "name", "username", "password", "role", "date_added"],
    "Clients": ["id", "name", "date_added"],
    "Assets": ["id", "name", "date_added"],
    "TimeEntries": ["user_id", "client_id", "date", "hours", "week_start"],
    "ProductionEntries": ["user_id", "client_id", "date", "asset_id", "amount"],
    "SubmittedWeeks": ["user_id", "week_start", "status", "submitted_at"]
}

# --- GOOGLE SHEETS CONNECTION ---

def get_sheet_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
    except:
        key_dict = json.loads(st.secrets["textkey"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    return gspread.authorize(creds)

def init_db():
    try:
        client = get_sheet_client()
        sh = client.open_by_url(SHEET_URL)
    except Exception as e:
        st.error(f"❌ Connection Error: {e}")
        st.stop()

    try:
        existing_titles = [w.title for w in sh.worksheets()]
        for tab_name, headers in REQUIRED_TABS.items():
            if tab_name not in existing_titles:
                ws = sh.add_worksheet(title=tab_name, rows=100, cols=20)
                ws.append_row(headers)
                if tab_name == "Users":
                    ws.append_row([1, "Administrator", "admin", "admin", "Admin", str(date.today())])
    except Exception as e:
        st.error(f"Database Init Error: {e}")

# --- DATA FUNCTIONS ---

@st.cache_data(ttl=600)
def load_data(tab_name):
    client = get_sheet_client()
    try:
        sh = client.open_by_url(SHEET_URL)
        worksheet = sh.worksheet(tab_name)
        data = worksheet.get_all_records()
        
        expected_cols = REQUIRED_TABS.get(tab_name, [])
        if not data:
            return pd.DataFrame(columns=expected_cols)
            
        df = pd.DataFrame(data)
        
        for col in expected_cols:
            if col not in df.columns:
                df[col] = None

        for col in ['id', 'user_id', 'client_id', 'asset_id', 'hours', 'amount']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        return df
    except Exception:
        time.sleep(2)
        return pd.DataFrame(columns=REQUIRED_TABS.get(tab_name, []))

def save_data(tab_name, df):
    client = get_sheet_client()
    sh = client.open_by_url(SHEET_URL)
    worksheet = sh.worksheet(tab_name)
    worksheet.clear()
    
    expected_cols = REQUIRED_TABS.get(tab_name, [])
    valid_cols = [c for c in expected_cols if c in df.columns]
    
    worksheet.update([df[valid_cols].columns.values.tolist()] + df[valid_cols].values.tolist())
    load_data.clear()

def generate_id(df):
    if df.empty or 'id' not in df.columns: return 1
    return int(df['id'].max()) + 1

# --- UTILS ---

def get_current_week_start():
    today = date.today()
    return today - timedelta(days=today.weekday())

def get_week_dates(start_date):
    return [start_date + timedelta(days=i) for i in range(7)]

# --- UI PAGES ---

def page_my_timesheet(user):
    st.header("📄 My Timesheet")
    st.caption(f"Logged in as: {user['name']}")
    st.divider()

    col1, col2 = st.columns([2, 5])
    with col1:
        default_start = get_current_week_start()
        selected_week = st.date_input("Week commencing", default_start)
        week_start_str = str(selected_week - timedelta(days=selected_week.weekday()))
    
    week_dates = get_week_dates(selected_week - timedelta(days=selected_week.weekday()))
    week_dates_str = [str(d) for d in week_dates] # For dropdowns

    # --- LOCKING / UNLOCK LOGIC ---
    subs_df = load_data("SubmittedWeeks")
    is_locked = False
    lock_status = ""
    
    if not subs_df.empty:
        match = subs_df[(subs_df['user_id'] == user['id']) & (subs_df['week_start'] == week_start_str)]
        if not match.empty:
            is_locked = True
            lock_status = match.iloc[0]['status']

    if is_locked:
        if lock_status == "Unlock Requested":
            st.warning(f"🔒 Unlock requested for {week_start_str}. Waiting for Admin approval.")
        else:
            c_lock1, c_lock2 = st.columns([3, 1])
            c_lock1.info(f"🔒 Week of {week_start_str} is submitted.")
            if c_lock2.button("🔓 Request Unlock"):
                idx = match.index[0]
                subs_df.at[idx, 'status'] = "Unlock Requested"
                save_data("SubmittedWeeks", subs_df)
                st.success("Request sent to Admin.")
                time.sleep(1)
                st.rerun()

    clients_df = load_data("Clients")
    time_df = load_data("TimeEntries")
    assets_df = load_data("Assets")
    
    current_entries = pd.DataFrame()
    if not time_df.empty:
        current_entries = time_df[(time_df['user_id'] == user['id']) & (time_df['week_start'] == week_start_str)]
    
    active_client_ids = []
    if not current_entries.empty:
        active_client_ids = current_entries['client_id'].unique().tolist()

    if 'ts_clients' not in st.session_state or st.session_state.get('ts_week') != week_start_str:
        st.session_state['ts_clients'] = active_client_ids
        st.session_state['ts_week'] = week_start_str

    if not is_locked:
        if clients_df.empty:
            st.warning("No clients found. Ask an Admin to add clients.")
        else:
            avail_clients = clients_df[~clients_df['id'].isin(st.session_state['ts_clients'])]
            if not avail_clients.empty:
                c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
                add_c = c1.selectbox("Add Client", avail_clients['name'], key="add_c_sel")
                if c2.button("Add Row"):
                    cid = int(avail_clients[avail_clients['name'] == add_c]['id'].values[0])
                    st.session_state['ts_clients'].append(cid)
                    st.rerun()

    st.write("")
    cols = st.columns([3] + [1]*7 + [1] + [0.5])
    cols[0].markdown("**Client**")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i, d in enumerate(week_dates): cols[i+1].markdown(f"**{d.day} {days[i]}**")
    cols[8].markdown("**Total**")
    st.divider()

    grand_total = 0
    with st.form("ts_grid"):
        if not st.session_state['ts_clients']:
            st.write("No clients added to this week.")
        
        for i, cid in enumerate(list(st.session_state['ts_clients'])):
            c_name_row = clients_df[clients_df['id'] == cid]
            c_name = c_name_row.iloc[0]['name'] if not c_name_row.empty else "Unknown"

            r_cols = st.columns([3] + [1]*7 + [1] + [0.5], vertical_alignment="center")
            r_cols[0].text_input("C", value=c_name, disabled=True, label_visibility="collapsed", key=f"d_{cid}")
            
            row_sum = 0
            for j, d in enumerate(week_dates):
                val = 0.0
                if not current_entries.empty:
                    match = current_entries[(current_entries['client_id'] == cid) & (current_entries['date'] == str(d))]
                    if not match.empty: val = float(match.iloc[0]['hours'])
                
                new_v = r_cols[j+1].number_input("H", min_value=0.0, step=0.5, value=val, key=f"h_{cid}_{d}", label_visibility="collapsed", disabled=is_locked)
                row_sum += new_v
            
            r_cols[8].markdown(f"**{row_sum:g}**")
            grand_total += row_sum
            
            if not is_locked:
                if r_cols[9].form_submit_button("❌", help="Remove row", key=f"remove_btn_{i}"):
                    st.session_state['ts_clients'].remove(cid)
                    st.rerun()
            
            st.markdown("---")
        
        st.write(f"**Weekly Total: {grand_total:g}**")
        
        if st.form_submit_button("💾 Save Hours", disabled=is_locked, type="primary"):
            new_rows = []
            for cid in st.session_state['ts_clients']:
                for d in week_dates:
                    key = f"h_{cid}_{d}"
                    if key in st.session_state:
                        h = st.session_state[key]
                        if h > 0:
                            new_rows.append({
                                "user_id": int(user['id']), "client_id": int(cid), "date": str(d), 
                                "hours": float(h), "week_start": week_start_str
                            })
            
            if not time_df.empty:
                clean_df = time_df[~((time_df['user_id'] == user['id']) & (time_df['week_start'] == week_start_str))]
            else:
                clean_df = pd.DataFrame(columns=["user_id", "client_id", "date", "hours", "week_start"])
            
            final_df = pd.concat([clean_df, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else clean_df
            save_data("TimeEntries", final_df)
            st.success("Saved Hours!")
            st.rerun()

    # --- PRODUCTION LIST (UPDATED) ---
    st.divider()
    st.subheader("📦 Production List")
    st.caption("Add or edit assets produced this week. These will lock upon submission.")

    prod_df = load_data("ProductionEntries")
    
    # Filter prod entries for THIS week and THIS user
    current_prod = pd.DataFrame()
    if not prod_df.empty:
        # Check if dates fall within this week
        mask_user = prod_df['user_id'] == user['id']
        mask_date = prod_df['date'].isin(week_dates_str)
        current_prod = prod_df[mask_user & mask_date].copy()

    # Prepare Display Dataframe (Map IDs to Names)
    display_data = []
    if not current_prod.empty:
        for _, row in current_prod.iterrows():
            c_name = ""
            a_name = ""
            if not clients_df.empty:
                c_match = clients_df[clients_df['id'] == row['client_id']]
                if not c_match.empty: c_name = c_match.iloc[0]['name']
            if not assets_df.empty:
                a_match = assets_df[assets_df['id'] == row['asset_id']]
                if not a_match.empty: a_name = a_match.iloc[0]['name']
            
            display_data.append({
                "Date": row['date'],
                "Client": c_name,
                "Asset": a_name,
                "Amount": int(row['amount'])
            })
    
    # FIX: Ensure DataFrame has columns even if empty
    if display_data:
        df_display = pd.DataFrame(display_data)
    else:
        df_display = pd.DataFrame(columns=["Date", "Client", "Asset", "Amount"])

    # Configuration for the Editor
    client_options = clients_df['name'].tolist() if not clients_df.empty else []
    asset_options = assets_df['name'].tolist() if not assets_df.empty else []

    edited_prod_df = st.data_editor(
        df_display,
        num_rows="dynamic",
        disabled=is_locked,
        column_config={
            "Date": st.column_config.SelectboxColumn("Date", options=week_dates_str, required=True, width="medium"),
            "Client": st.column_config.SelectboxColumn("Client", options=client_options, required=True, width="medium"),
            "Asset": st.column_config.SelectboxColumn("Asset", options=asset_options, required=True, width="medium"),
            "Amount": st.column_config.NumberColumn("Amount", min_value=1, step=1, required=True, width="small")
        },
        use_container_width=True,
        key="prod_editor"
    )

    if not is_locked:
        if st.button("💾 Save Assets"):
            # Reconstruct the Dataframe to save (Map Names back to IDs)
            new_prod_rows = []
            
            # Helper lookups
            c_map = dict(zip(clients_df['name'], clients_df['id'])) if not clients_df.empty else {}
            a_map = dict(zip(assets_df['name'], assets_df['id'])) if not assets_df.empty else {}

            for _, row in edited_prod_df.iterrows():
                if row['Client'] and row['Asset'] and row['Date']:
                    cid = c_map.get(row['Client'])
                    aid = a_map.get(row['Asset'])
                    if cid and aid:
                        new_prod_rows.append({
                            "user_id": int(user['id']),
                            "client_id": int(cid),
                            "date": str(row['Date']),
                            "asset_id": int(aid),
                            "amount": int(row['Amount'])
                        })
            
            # Delete OLD entries for this week/user and Insert NEW
            # 1. Filter out everything from DB that matches this user AND this week's dates
            if not prod_df.empty:
                # Keep rows that are NOT (this user AND this week)
                mask_delete = (prod_df['user_id'] == user['id']) & (prod_df['date'].isin(week_dates_str))
                prod_db_clean = prod_df[~mask_delete]
            else:
                prod_db_clean = pd.DataFrame(columns=["user_id", "client_id", "date", "asset_id", "amount"])

            # 2. Concat
            final_prod_db = pd.concat([prod_db_clean, pd.DataFrame(new_prod_rows)], ignore_index=True)
            save_data("ProductionEntries", final_prod_db)
            st.success("Assets List Updated!")
            time.sleep(1)
            st.rerun()

    st.divider()
    st.markdown("### Final Submission")
    if grand_total > 0:
        if st.button("✅ Submit Timesheet", type="primary", disabled=is_locked):
            new_sub = {"user_id": int(user['id']), "week_start": week_start_str, "status": "Submitted", "submitted_at": str(datetime.datetime.now())}
            subs_df = pd.concat([subs_df, pd.DataFrame([new_sub])], ignore_index=True)
            save_data("SubmittedWeeks", subs_df)
            st.balloons()
            st.rerun()
    else:
        st.caption("Save hours (> 0) to enable submission.")

def page_workload_details(user):
    st.header("📊 Workload Details")
    
    c1, c2 = st.columns(2)
    today = date.today()
    month_names = list(calendar.month_name)[1:]
    sel_month = c1.selectbox("Month", month_names, index=today.month-1)
    sel_year = c2.selectbox("Year", range(2024, 2030), index=today.year - 2024)
    
    month_idx = month_names.index(sel_month) + 1
    start_date = date(sel_year, month_idx, 1)
    last_day = calendar.monthrange(sel_year, month_idx)[1]
    end_date = date(sel_year, month_idx, last_day)
    
    time_df = load_data("TimeEntries")
    users_df = load_data("Users")
    clients_df = load_data("Clients")
    prod_df = load_data("ProductionEntries")
    assets_df = load_data("Assets")

    mask = (time_df['date'] >= str(start_date)) & (time_df['date'] <= str(end_date))
    filtered_time = time_df.loc[mask] if not time_df.empty else pd.DataFrame()

    if user['role'] != 'Admin':
        if not filtered_time.empty:
            filtered_time = filtered_time[filtered_time['user_id'] == user['id']]

    st.divider()
    st.subheader("Statistics by Employee")
    if not filtered_time.empty and not users_df.empty:
        emp_merge = pd.merge(filtered_time, users_df, left_on='user_id', right_on='id')
        emp_pivot = emp_merge.pivot_table(index='name', columns='date', values='hours', aggfunc='sum', fill_value=0)
        emp_pivot['Total'] = emp_pivot.sum(axis=1)
        st.dataframe(emp_pivot, use_container_width=True)
    else:
        st.info("No time data.")

    st.divider()
    st.subheader("Statistics by Client")
    if not filtered_time.empty and not clients_df.empty:
        cli_merge = pd.merge(filtered_time, clients_df, left_on='client_id', right_on='id')
        cli_pivot = cli_merge.pivot_table(index='name', columns='date', values='hours', aggfunc='sum', fill_value=0)
        cli_pivot['Total'] = cli_pivot.sum(axis=1)
        st.dataframe(cli_pivot, use_container_width=True)
    else:
        st.info("No time data.")

    st.divider()
    if not prod_df.empty and 'date' in prod_df.columns:
        p_mask = (prod_df['date'] >= str(start_date)) & (prod_df['date'] <= str(end_date))
        filtered_prod = prod_df.loc[p_mask]
    else:
        filtered_prod = pd.DataFrame()
    
    if user['role'] != 'Admin':
        if not filtered_prod.empty:
            filtered_prod = filtered_prod[filtered_prod['user_id'] == user['id']]

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Assets Produced (Total)**")
        if not filtered_prod.empty and not assets_df.empty:
            a_merge = pd.merge(filtered_prod, assets_df, left_on='asset_id', right_on='id')
            a_stats = a_merge.groupby('name')['amount'].sum().reset_index()
            a_stats.columns = ['Asset', 'Amount']
            st.dataframe(a_stats, use_container_width=True, hide_index=True)
        else:
            st.info("No assets produced.")

    with col_b:
        st.markdown("**Assets per Client**")
        if not clients_df.empty:
            c_list = clients_df['name'].tolist()
            sel_cli = st.selectbox("Select Client", c_list)
            
            if not filtered_prod.empty and not assets_df.empty:
                cid_row = clients_df[clients_df['name'] == sel_cli]
                if not cid_row.empty:
                    cid = cid_row['id'].values[0]
                    c_prod = filtered_prod[filtered_prod['client_id'] == cid]
                    if not c_prod.empty:
                        ca_merge = pd.merge(c_prod, assets_df, left_on='asset_id', right_on='id')
                        ca_stats = ca_merge.groupby('name')['amount'].sum().reset_index()
                        ca_stats.columns = ['Asset', 'Amount']
                        st.dataframe(ca_stats, use_container_width=True, hide_index=True)
                    else:
                        st.info(f"No assets for {sel_cli}")
                else:
                    st.warning("Client error.")
        else:
            st.warning("No clients.")

def page_submitted_timesheets(user):
    st.header("🗂 Submitted Timesheets")
    subs_df = load_data("SubmittedWeeks")
    users_df = load_data("Users")
    time_df = load_data("TimeEntries")
    clients_df = load_data("Clients")
    
    if subs_df.empty:
        st.info("No submissions.")
        return

    full = pd.merge(subs_df, users_df[['id', 'name']], left_on='user_id', right_on='id')
    
    if user['role'] != 'Admin':
        full = full[full['user_id'] == user['id']]

    if full.empty:
        st.info("No submissions found.")
        return

    st.markdown("### Result")
    h1, h2, h3, h4, h5 = st.columns([2, 2, 2, 2, 2])
    h1.markdown("**Employee**")
    h2.markdown("**Week**")
    h3.markdown("**Date**")
    h4.markdown("**Status**")
    h5.markdown("**Action**")
    st.divider()

    for idx, row in full.iterrows():
        c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
        c1.write(row['name'])
        c2.write(row['week_start'])
        c3.write(row['submitted_at'])
        c4.write(row['status'])
        
        # Admin Action for Unlock Requests
        if user['role'] == "Admin" and row['status'] == "Unlock Requested":
            if c5.button("🔓 UNLOCK", key=f"unl_{idx}", type="primary"):
                # Remove the specific submission row
                target_uid = row['user_id']
                target_week = row['week_start']
                subs_df = subs_df[~((subs_df['user_id'] == target_uid) & (subs_df['week_start'] == target_week))]
                save_data("SubmittedWeeks", subs_df)
                st.success("Unlocked successfully!")
                time.sleep(1)
                st.rerun()
        else:
            if c5.button("Open", key=f"op_{idx}"):
                st.session_state['view_sub_id'] = row['user_id']
                st.session_state['view_sub_week'] = row['week_start']
                st.rerun()
        st.markdown("---")

    if 'view_sub_id' in st.session_state:
        st.divider()
        v_uid = st.session_state['view_sub_id']
        v_week = st.session_state['view_sub_week']
        st.subheader(f"Details for {v_week}")
        
        details = time_df[(time_df['user_id'] == v_uid) & (time_df['week_start'] == v_week)]
        if not details.empty:
            d_merged = pd.merge(details, clients_df[['id', 'name']], left_on='client_id', right_on='id')
            pivot = d_merged.pivot_table(index='name', columns='date', values='hours', fill_value=0)
            st.dataframe(pivot, use_container_width=True)
        else:
            st.warning("Empty submission.")
            
        if st.button("Close"):
            del st.session_state['view_sub_id']
            st.rerun()

def page_manage_users(current_user):
    st.header("👥 Manage Users")
    users_df = load_data("Users")
    
    with st.form("add_u"):
        st.subheader("Add new user")
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name")
        uname = c2.text_input("Username")
        pwd = c3.text_input("Password", type="password")
        if st.form_submit_button("Add User"):
            if not users_df.empty and uname in users_df['username'].values:
                st.error("Username taken")
            else:
                new_id = generate_id(users_df)
                new_u = {"id": new_id, "name": name, "username": uname, "password": pwd, "role": "Employee", "date_added": str(date.today())}
                save_data("Users", pd.concat([users_df, pd.DataFrame([new_u])], ignore_index=True))
                st.success("User Added")
                st.rerun()
    
    st.divider()
    st.subheader("User List (Edit / Delete)")
    
    if not users_df.empty:
        display_df = users_df.copy()
        edited_df = st.data_editor(
            display_df,
            column_config={
                "id": st.column_config.NumberColumn(disabled=True),
                "username": st.column_config.TextColumn(disabled=True, help="Usernames cannot be changed."),
                "password": st.column_config.TextColumn(disabled=False),
                "role": st.column_config.SelectboxColumn(options=["Admin", "Employee"], required=True),
            },
            num_rows="dynamic",
            key="user_editor",
            use_container_width=True
        )

        if st.button("💾 Save User Changes"):
            if len(edited_df) < len(users_df):
                deleted_ids = set(users_df['id']) - set(edited_df['id'])
                if current_user['id'] in deleted_ids:
                    st.error("❌ You cannot delete yourself!")
                else:
                    save_data("Users", edited_df)
                    st.success("Users updated successfully!")
                    st.rerun()
            else:
                save_data("Users", edited_df)
                st.success("Users updated successfully!")
                st.rerun()

def page_clients_assets():
    st.header("Clients & Assets")
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("Clients")
        clients_df = load_data("Clients")
        with st.form("add_cli"):
            nc = st.text_input("New Client Name")
            if st.form_submit_button("Add Client"):
                new_c = {"id": generate_id(clients_df), "name": nc, "date_added": str(date.today())}
                save_data("Clients", pd.concat([clients_df, pd.DataFrame([new_c])], ignore_index=True))
                st.rerun()
        if not clients_df.empty:
            edited_cli = st.data_editor(
                clients_df,
                column_config={"id": st.column_config.NumberColumn(disabled=True)},
                num_rows="dynamic",
                key="cli_editor",
                use_container_width=True
            )
            if st.button("Save Clients"):
                save_data("Clients", edited_cli)
                st.success("Clients updated!")
                st.rerun()

    with c2:
        st.subheader("Assets")
        assets_df = load_data("Assets")
        with st.form("add_ass"):
            na = st.text_input("New Asset Name")
            if st.form_submit_button("Add Asset"):
                new_a = {"id": generate_id(assets_df), "name": na, "date_added": str(date.today())}
                save_data("Assets", pd.concat([assets_df, pd.DataFrame([new_a])], ignore_index=True))
                st.rerun()
        if not assets_df.empty:
            edited_ass = st.data_editor(
                assets_df,
                column_config={"id": st.column_config.NumberColumn(disabled=True)},
                num_rows="dynamic",
                key="ass_editor",
                use_container_width=True
            )
            if st.button("Save Assets"):
                save_data("Assets", edited_ass)
                st.success("Assets updated!")
                st.rerun()

def page_my_profile(user):
    st.header("👤 My Profile")
    st.caption("Update your personal details here.")
    users_df = load_data("Users")
    
    with st.form("upd_me"):
        n_name = st.text_input("Name", value=user['name'])
        n_user = st.text_input("Username", value=user['username'], disabled=True, help="Contact Admin to change username.")
        n_pass = st.text_input("New Password", value=user['password'], type="password")
        if st.form_submit_button("Save Changes"):
            idx = users_df[users_df['id'] == user['id']].index[0]
            users_df.at[idx, 'name'] = n_name
            users_df.at[idx, 'password'] = n_pass
            save_data("Users", users_df)
            user['name'] = n_name
            user['password'] = n_pass
            st.session_state['user'] = user
            st.success("Profile Updated!")
            time.sleep(1)
            st.rerun()

# --- MAIN ---

def main():
    try:
        init_db()
    except Exception:
        pass
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    if not st.session_state['logged_in']:
        st.title("MyTracker Login")
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Log In"):
                users_df = load_data("Users")
                if not users_df.empty:
                    match = users_df[(users_df['username'] == u) & (users_df['password'] == p)]
                    if not match.empty:
                        st.session_state['logged_in'] = True
                        st.session_state['user'] = match.iloc[0].to_dict()
                        st.rerun()
                    else: st.error("Invalid Login")
                else: st.error("Database Empty")
        return

    user = st.session_state['user']
    role = user['role']
    
    with st.sidebar:
        st.title("MyTracker")
        st.write(f"👤 {user['name']}")
        
        opts = ["My timesheet", "Workload details", "Submitted timesheets", "My Profile"]
        if role == "Admin":
            opts += ["Manage users", "Clients and assets"]
            
        page = st.radio("Menu", opts)
        if st.button("Logout"):
            st.session_state['logged_in'] = False
            st.rerun()

    if page == "My timesheet": page_my_timesheet(user)
    elif page == "Workload details": page_workload_details(user)
    elif page == "Submitted timesheets": page_submitted_timesheets(user)
    elif page == "My Profile": page_my_profile(user)
    elif page == "Manage users": 
        if role == "Admin": page_manage_users(user)
    elif page == "Clients and assets":
        if role == "Admin": page_clients_assets()

if __name__ == "__main__":
    main()
