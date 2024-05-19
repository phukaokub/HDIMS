from cryptography.fernet import Fernet
import json
import PyPDF2
import subprocess
import os
import tempfile
import base64
import timeit
from google.cloud import storage
import concurrent.futures
from math import ceil

# Define paths
oldkey_path = "/home/phukaokk/SIIT Project/HDIMS/DataExchange/Data_Owner"
cpabe_path = "/home/phukaokk/SIIT Project/HDIMS/DataExchange/cpabe-0.11"
base_path = "/home/phukaokk/SIIT Project/HDIMS/DataExchange/Access_Requester"
pub_key_path = os.path.join(oldkey_path, "pub_key")
master_key_path = os.path.join(oldkey_path, "master_key")
priv_key_dir = os.path.join(base_path, "cpabe_keys")

# Download data.json from GCS before processing
bucket_name = "hospital-a"
object_name = "proxy-test.json"
local_data_path = "proxy-test.json"

def download_data_from_gcs(bucket_name, object_name, local_file_path):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.download_to_filename(local_file_path)

def decrypt_file(encrypted_content_base64, key):
    f = Fernet(key)
    encrypted_content = base64.b64decode(encrypted_content_base64.encode())
    decrypted_content = f.decrypt(encrypted_content)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
        temp_file.write(decrypted_content)
        temp_file_path = temp_file.name
    return temp_file_path

def generate_private_key(attributes, priv_name):
    priv_key_path = os.path.join(priv_key_dir, priv_name)
    cpabe_keygen_path = os.path.join(cpabe_path, 'cpabe-keygen')
    os.makedirs(priv_key_dir, exist_ok=True)
    result = subprocess.run(
        [cpabe_keygen_path, '-o', priv_key_path, pub_key_path, master_key_path] + attributes,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"Error generating private key: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
    with open(priv_key_path, "rb") as f:
        private_key = base64.b64encode(f.read()).decode("utf-8")
    return private_key

def decrypt_key(encrypted_key_base64, priv_key_name):
    cpabe_dec_path = os.path.join(cpabe_path, 'cpabe-dec')
    encrypted_key_path = os.path.join(priv_key_dir, "encrypted_key.cpabe")
    with open(encrypted_key_path, "wb") as f:
        f.write(base64.b64decode(encrypted_key_base64))
    decrypted_key_path = os.path.join(base_path, "decrypted_key")
    priv_key_path = os.path.join(priv_key_dir, priv_key_name)
    result = subprocess.run(
        [cpabe_dec_path, pub_key_path, priv_key_path, encrypted_key_path, '-o', decrypted_key_path, '-k'],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"Error decrypting key 70: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
    with open(decrypted_key_path, "rb") as f:
        decrypted_key = f.read()
    return decrypted_key

def encrypt_key(key, policy):
    with tempfile.NamedTemporaryFile(delete=False) as temp_key_file:
        temp_key_file.write(key)
        temp_key_file.flush()
        cpabe_enc_path = os.path.join(cpabe_path, 'cpabe-enc')
        encrypted_key_path = os.path.join(priv_key_dir, "reencrypted_key.cpabe")
        result = subprocess.run(
            [cpabe_enc_path, '-k', pub_key_path, temp_key_file.name, policy, '-o', encrypted_key_path],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"Error encrypting key: {result.stderr}")
            raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)
    with open(encrypted_key_path, "rb") as f:
        encrypted_key = base64.b64encode(f.read()).decode("utf-8")
    return encrypted_key

def reencrypt_entry(entry, reencryption_total_time, proxy_id, index):
    encrypted_content_base64 = entry["files"][0]["CT_1"]
    encrypted_key_base64 = entry["files"][0]["CT_2"]

    start_time = timeit.default_timer()
    try:
        decrypted_key = decrypt_key(encrypted_key_base64, priv_name)
    except subprocess.CalledProcessError as e:
        print(f"Error decrypting key 102: {e}")
        return

    stop_time = timeit.default_timer()
    decryption_time = stop_time - start_time

    decrypted_file_path = decrypt_file(encrypted_content_base64, decrypted_key)

    with open(decrypted_file_path, "rb") as file:
        with open(f"decrypted_{index}.pdf", "wb") as decrypted:
            decrypted.write(file.read())

    with open(decrypted_file_path, "rb") as decrypted:
        pdf_reader = PyPDF2.PdfReader(decrypted)
        print(f"PDF {index} metadata:", pdf_reader.metadata)

    # Use a fixed policy that matches the attributes
    new_policy = "(admin and it_department) or (developer and finance)"
    start_reenc_time = timeit.default_timer()
    re_encrypted_key = encrypt_key(decrypted_key, new_policy)
    stop_reenc_time = timeit.default_timer()
    reenc_time = stop_reenc_time - start_reenc_time

    new_priv_name = 'AR_repriv'
    new_attributes = ['admin', 'it_department']
    generate_private_key(new_attributes, new_priv_name)
    start_redec_time = timeit.default_timer()
    decrypted_reencrypted_key = decrypt_key(re_encrypted_key, new_priv_name)
    stop_redec_time = timeit.default_timer()
    redecryption_time = stop_redec_time - start_redec_time

    # Accumulate the total re-encryption time
    reencryption_total_time += (decryption_time + reenc_time + redecryption_time)
    # Print re-encryption time for the current entry
    print(f"Re-encryption Time for entry {index}: {reencryption_total_time} seconds")

    return reencryption_total_time

# Start recording the total time
total_start_time = timeit.default_timer()

# Download data.json from GCS before processing
download_start_time = timeit.default_timer()
download_data_from_gcs(bucket_name, object_name, local_data_path)
download_stop_time = timeit.default_timer()
download_time = download_stop_time - download_start_time

with open(local_data_path, "r") as file:
    data = json.load(file)

attributes = ['developer', 'it_department']
priv_name = 'AR_priv'
generate_private_key(attributes, priv_name)

reencryption_total_time = 0  # Initialize total re-encryption time

print("Select an option:")
print("1. Perform re-encryption sequentially")
print("2. Perform re-encryption in parallel")

choice = input("Enter your choice: ")

if choice == "1":
    for index, entry in enumerate(data[:20]):
        reencryption_total_time = reencrypt_entry(entry, reencryption_total_time, None, index)

elif choice == "2":
    # Split the data into 5 chunks
    chunk_size = ceil(len(data[:20]) / 5)
    chunks = [data[:20][i:i+chunk_size] for i in range(0, len(data[:20]), chunk_size)]

    # Create a list of futures
    futures = []
    with concurrent.futures.ProcessPoolExecutor() as executor:
        for proxy_id, chunk in enumerate(chunks):
            for index, entry in enumerate(chunk):
                futures.append(executor.submit(reencrypt_entry, entry, reencryption_total_time, proxy_id, index+proxy_id*chunk_size))
                print(f"Re-encryption task for entry {index+proxy_id*chunk_size} in chunk {proxy_id} submitted")

    # Collect the results
    for future in concurrent.futures.as_completed(futures):
        reencryption_total_time = future.result()

else:
    print("Invalid choice. Please enter 1 or 2.")

# Print total re-encryption time
print(f"Total Re-encryption Time: {reencryption_total_time} seconds")

# Stop recording the total time
total_stop_time = timeit.default_timer()
total_time = total_stop_time - total_start_time

# Print total time
print(f"Total Time: {total_time} seconds")
