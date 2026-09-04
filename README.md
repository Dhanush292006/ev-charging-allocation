# ChargeFlow

Streamlit dashboard for rule-based EV charging station allocation.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app uses live Open Charge Map station data and OSRM driving routes. Enter latitude and longitude manually; the default coordinates are central Chennai.

## Publish with Streamlit Community Cloud

1. Create a GitHub repository and upload `app.py` and `requirements.txt`.
2. Open [share.streamlit.io](https://share.streamlit.io/) and sign in with GitHub.
3. Select the repository, branch, and `app.py` as the main file.
4. Deploy the app.

The existing HTML/CSS/JavaScript prototype is retained in the repository as the original browser version.
