from src.console import console
import os
import pyimgbox
import asyncio
import requests
import glob
import base64
import time
import re
import gc
import json
from concurrent.futures import ThreadPoolExecutor
import traceback
import httpx
import aiofiles

try:
    from data.config import config
except Exception:
    print("[red]Erro: não foi possível importar a configuração. Verifique se o arquivo de config está no local correto.[/red]")
    print("[red]Siga as instruções de configuração: https://github.com/Audionut/Upload-Assistant")
    traceback.print_exc()
    exit(1)


async def upload_image_task(args):
    image, img_host, config, meta = args
    try:
        timeout = 60  # Default timeout
        img_url, raw_url, web_url = None, None, None

        if img_host == "imgbox":
            try:
                image_list = await imgbox_upload(os.getcwd(), [image], meta, return_dict={})
                if image_list and all(
                    'img_url' in img and 'raw_url' in img and 'web_url' in img for img in image_list
                ):
                    img_url = image_list[0]['img_url']
                    raw_url = image_list[0]['raw_url']
                    web_url = image_list[0]['web_url']
                else:
                    return {
                        'status': 'failed',
                        'reason': "Imgbox upload failed. No valid URLs returned."
                    }
            except Exception as e:
                return {
                    'status': 'failed',
                    'reason': f"Error during Imgbox upload: {str(e)}"
                }

        elif img_host == "ptpimg":
            try:
                payload = {
                    'format': 'json',
                    'api_key': config['DEFAULT']['ptpimg_api'].strip()
                }
            except KeyError:
                return {'status': 'failed', 'reason': 'Missing ptpimg API key in config'}

            try:
                async with httpx.AsyncClient() as client:
                    async with aiofiles.open(image, 'rb') as file:
                        files = {'file-upload[0]': (os.path.basename(image), await file.read())}
                        headers = {'referer': 'https://ptpimg.me/index.php'}
                        if meta.get('debug'):
                            console.print(f"[cyan][ptpimg] Cabeçalhos: {headers}[/cyan]")
                            console.print(f"[cyan][ptpimg] Arquivos: {list(files.keys())}[/cyan]")

                    try:
                        response = await client.post(
                            "https://ptpimg.me/upload.php",
                            headers=headers,
                            data=payload,
                            files=files,
                            timeout=timeout
                        )
                        if meta.get('debug'):
                            console.print(f"[cyan][ptpimg] Status da resposta: {response.status_code}[/cyan]")
                            console.print(f"[cyan][ptpimg] Corpo da resposta: {response.text[:500]}[/cyan]")

                        response.raise_for_status()
                        response_data = response.json()
                        if meta.get('debug'):
                            console.print(f"[cyan][ptpimg] JSON de resposta: {response_data}[/cyan]")

                        if not response_data or not isinstance(response_data, list) or 'code' not in response_data[0]:
                            return {'status': 'failed', 'reason': "Invalid JSON response from ptpimg"}

                        code = response_data[0]['code']
                        ext = response_data[0]['ext']
                        if meta.get('debug'):
                            console.print(f"[cyan][ptpimg] Código da imagem: {code}, extensão: {ext}[/cyan]")
                        img_url = f"https://ptpimg.me/{code}.{ext}"
                        raw_url = img_url
                        web_url = img_url

                    except httpx.TimeoutException:
                        console.print("[red][ptpimg] A solicitação expirou.")
                        return {'status': 'failed', 'reason': 'Request timed out'}
                    except ValueError as e:
                        console.print(f"[red][ptpimg] ValueError: {str(e)}")
                        return {'status': 'failed', 'reason': f"Request failed: {str(e)}"}
                    except json.JSONDecodeError as e:
                        console.print(f"[red][ptpimg] JSONDecodeError: {str(e)}")
                        return {'status': 'failed', 'reason': 'Invalid JSON response from ptpimg'}
            except Exception as e:
                console.print(f"[red][ptpimg] Exceção: {str(e)}")
                return {'status': 'failed', 'reason': f"Error during ptpimg upload: {str(e)}"}

        elif img_host == "imgbb":
            url = "https://api.imgbb.com/1/upload"
            try:
                async with aiofiles.open(image, "rb") as img_file:
                    encoded_image = base64.b64encode(await img_file.read()).decode('utf8')

                data = {
                    'key': config['DEFAULT']['imgbb_api'],
                    'image': encoded_image,
                }

                async with httpx.AsyncClient() as client:
                    response = await client.post(url, data=data, timeout=timeout)
                    response_data = response.json()
                    if response.status_code != 200 or not response_data.get('success'):
                        console.print("[yellow]imgbb falhou, tentando o próximo host de imagem")
                        return {'status': 'failed', 'reason': 'imgbb upload failed'}

                    img_url = response_data['data'].get('medium', {}).get('url') or response_data['data']['thumb']['url']
                    raw_url = response_data['data']['image']['url']
                    web_url = response_data['data']['url_viewer']

                    if meta['debug']:
                        console.print(f"[green]URLs da imagem: img_url={img_url}, raw_url={raw_url}, web_url={web_url}")

                    return {'status': 'success', 'img_url': img_url, 'raw_url': raw_url, 'web_url': web_url}

            except httpx.TimeoutException:
                console.print("[red]Tempo de solicitação excedido. O servidor demorou para responder.")
                return {'status': 'failed', 'reason': 'Request timed out'}

            except ValueError as e:  # JSON decoding error
                console.print(f"[red]Resposta JSON inválida: {e}")
                return {'status': 'failed', 'reason': 'Invalid JSON response'}

            except httpx.RequestError as e:
                console.print(f"[red]Falha na solicitação: {e}")
                return {'status': 'failed', 'reason': str(e)}

        elif img_host == "dalexni":
            url = "https://dalexni.com/1/upload"
            try:
                with open(image, "rb") as img_file:
                    encoded_image = base64.b64encode(img_file.read()).decode('utf8')

                data = {
                    'key': config['DEFAULT']['dalexni_api'],
                    'image': encoded_image,
                }

                response = requests.post(url, data=data, timeout=timeout)
                response_data = response.json()
                if response.status_code != 200 or not response_data.get('success'):
                    console.print("[yellow]DALEXNI falhou, tentando o próximo host de imagem")
                    return {'status': 'failed', 'reason': 'DALEXNI upload failed'}

                img_url = response_data['data'].get('medium', {}).get('url') or response_data['data']['thumb']['url']
                raw_url = response_data['data']['image']['url']
                web_url = response_data['data']['url_viewer']

                if meta['debug']:
                    console.print(f"[green]URLs da imagem: img_url={img_url}, raw_url={raw_url}, web_url={web_url}")

                return {'status': 'success', 'img_url': img_url, 'raw_url': raw_url, 'web_url': web_url}

            except requests.exceptions.Timeout:
                console.print("[red]Tempo de solicitação excedido. O servidor demorou para responder.")
                return {'status': 'failed', 'reason': 'Request timed out'}

            except ValueError as e:  # JSON decoding error
                console.print(f"[red]Resposta JSON inválida: {e}")
                return {'status': 'failed', 'reason': 'Invalid JSON response'}

            except requests.exceptions.RequestException as e:
                console.print(f"[red]Falha na solicitação: {e}")
                return {'status': 'failed', 'reason': str(e)}

        elif img_host == "ptscreens":
            url = "https://ptscreens.com/api/1/upload"
            try:
                headers = {
                    'X-API-Key': config['DEFAULT']['ptscreens_api']
                }

                async with httpx.AsyncClient() as client:
                    async with aiofiles.open(image, 'rb') as file:
                        files = {
                            'source': ('file-upload[0]', await file.read())
                        }

                        response = await client.post(url, headers=headers, files=files, timeout=timeout)
                        response_data = response.json()

                        if response.status_code == 400:
                            console.print("[yellow]Envio ao ptscreens falhou: upload duplicado (400)")
                            return {'status': 'failed', 'reason': 'ptscreens duplicate'}

                        if response_data.get('status_code') != 200:
                            console.print("[yellow]ptscreens falhou")
                            return {'status': 'failed', 'reason': 'ptscreens upload failed'}

                        img_url = response_data['image']['medium']['url']
                        raw_url = response_data['image']['url']
                        web_url = response_data['image']['url_viewer']

                        if meta['debug']:
                            console.print(f"[green]URLs da imagem: img_url={img_url}, raw_url={raw_url}, web_url={web_url}")

            except httpx.TimeoutException:
                console.print("[red]Tempo de solicitação excedido. O servidor demorou para responder.")
                return {'status': 'failed', 'reason': 'Request timed out'}
            except httpx.RequestError as e:
                console.print(f"[red]Falha na solicitação: {e}")
                return {'status': 'failed', 'reason': str(e)}
            except ValueError as e:
                console.print(f"[red]Resposta JSON inválida do ptscreens: {e}")
                return {'status': 'failed', 'reason': 'Invalid JSON response'}

        elif img_host == "onlyimage":
            url = "https://onlyimage.org/api/1/upload"
            try:
                async with aiofiles.open(image, "rb") as img_file:
                    encoded_image = base64.b64encode(await img_file.read()).decode('utf8')

                data = {
                    'image': encoded_image
                }
                headers = {
                    'X-API-Key': config['DEFAULT']['onlyimage_api'],
                }

                async with httpx.AsyncClient() as client:
                    response = await client.post(url, data=data, headers=headers, timeout=timeout)
                    response_data = response.json()

                    if response.status_code != 200 or not response_data.get('success'):
                        console.print("[yellow]OnlyImage falhou, tentando o próximo host de imagem")
                        return {'status': 'failed', 'reason': 'OnlyImage upload failed'}

                    img_url = response_data['data']['medium']['url']
                    raw_url = response_data['data']['image']['url']
                    web_url = response_data['data']['url_viewer']

                    if meta['debug']:
                        console.print(f"[green]URLs da imagem: img_url={img_url}, raw_url={raw_url}, web_url={web_url}")

            except httpx.TimeoutException:
                console.print("[red]Tempo de solicitação excedido. O servidor demorou para responder.")
                return {'status': 'failed', 'reason': 'Request timed out'}
            except httpx.RequestError as e:
                console.print(f"[red]Falha na solicitação: {e}")
                return {'status': 'failed', 'reason': str(e)}
            except ValueError as e:
                console.print(f"[red]Resposta JSON inválida do OnlyImage: {e}")
                return {'status': 'failed', 'reason': 'Invalid JSON response'}

        elif img_host == "pixhost":
            url = "https://api.pixhost.to/images"
            try:
                data = {
                    'content_type': '0',
                    'max_th_size': 350
                }

                async with httpx.AsyncClient() as client:
                    async with aiofiles.open(image, 'rb') as file:
                        files = {
                            'img': ('file-upload[0]', await file.read())
                        }

                        response = await client.post(url, data=data, files=files, timeout=timeout)

                        if response.status_code != 200:
                            console.print(f"[yellow]pixhost falhou com código {response.status_code}, tentando o próximo host de imagem")
                            return {'status': 'failed', 'reason': f'pixhost upload failed with status code {response.status_code}'}

                        try:
                            response_data = response.json()
                            if 'th_url' not in response_data:
                                console.print("[yellow]pixhost falhou: formato de resposta inválido")
                                return {'status': 'failed', 'reason': 'Invalid response from pixhost'}

                            raw_url = response_data['th_url'].replace('https://t', 'https://img').replace('/thumbs/', '/images/')
                            img_url = response_data['th_url']
                            web_url = response_data['show_url']

                            if meta['debug']:
                                console.print(f"[green]URLs da imagem: img_url={img_url}, raw_url={raw_url}, web_url={web_url}")

                        except ValueError as e:
                            console.print(f"[red]Resposta JSON inválida do pixhost: {e}")
                            return {'status': 'failed', 'reason': 'Invalid JSON response'}

            except httpx.TimeoutException:
                console.print("[red]Solicitação ao pixhost excedeu o tempo. O servidor demorou para responder.")
                return {'status': 'failed', 'reason': 'Request timed out'}

            except httpx.RequestError as e:
                console.print(f"[red]Solicitação ao pixhost falhou: {e}")
                return {'status': 'failed', 'reason': str(e)}

        elif img_host == "lensdump":
            url = "https://lensdump.com/api/1/upload"
            data = {
                'image': base64.b64encode(open(image, "rb").read()).decode('utf8')
            }
            headers = {
                'X-API-Key': config['DEFAULT']['lensdump_api']
            }
            response = requests.post(url, data=data, headers=headers, timeout=timeout)
            response_data = response.json()
            if response_data.get('status_code') == 200:
                img_url = response_data['data']['image']['url']
                raw_url = response_data['data']['image']['url']
                web_url = response_data['data']['url_viewer']

        elif img_host == "zipline":
            url = config['DEFAULT'].get('zipline_url')
            api_key = config['DEFAULT'].get('zipline_api_key')

            if not url or not api_key:
                console.print("[red]Erro: faltando URL ou API key do Zipline nas configurações.")
                return {'status': 'failed', 'reason': 'Missing Zipline URL or API key'}

            try:
                with open(image, "rb") as img_file:
                    files = {'file': img_file}
                    headers = {
                        'Authorization': f'{api_key}',
                    }

                    response = requests.post(url, files=files, headers=headers, timeout=timeout)
                    if response.status_code == 200:
                        response_data = response.json()
                        if 'files' in response_data:
                            img_url = response_data['files'][0]
                            raw_url = img_url.replace('/u/', '/r/')
                            web_url = img_url.replace('/u/', '/r/')
                            return {
                                'status': 'success',
                                'img_url': img_url,
                                'raw_url': raw_url,
                                'web_url': web_url
                            }
                        else:
                            return {'status': 'failed', 'reason': 'No valid URL returned from Zipline'}

                    else:
                        return {'status': 'failed', 'reason': f"Zipline upload failed: {response.text}"}
            except requests.exceptions.Timeout:
                console.print("[red]Tempo de solicitação excedido. O servidor demorou para responder.")
                return {'status': 'failed', 'reason': 'Request timed out'}

            except ValueError as e:  # JSON decoding error
                console.print(f"[red]Resposta JSON inválida: {e}")
                return {'status': 'failed', 'reason': 'Invalid JSON response'}

            except requests.exceptions.RequestException as e:
                console.print(f"[red]Falha na solicitação: {e}")
                return {'status': 'failed', 'reason': str(e)}

        elif img_host == "passtheimage":
            url = "https://passtheima.ge/api/1/upload"
            try:
                pass_api_key = config['DEFAULT'].get('passtheima_ge_api')
                if not pass_api_key:
                    console.print("[red]Chave de API do Passtheimage não encontrada na configuração.")
                    return {'status': 'failed', 'reason': 'Missing Passtheimage API key'}

                headers = {
                    'X-API-Key': pass_api_key
                }

                async with httpx.AsyncClient() as client:
                    async with aiofiles.open(image, 'rb') as img_file:
                        files = {'source': (os.path.basename(image), await img_file.read())}
                        response = await client.post(url, headers=headers, files=files, timeout=timeout)

                        if 'application/json' in response.headers.get('Content-Type', ''):
                            response_data = response.json()
                        else:
                            console.print(f"[red]Passtheimage não retornou JSON. Status: {response.status_code}, Resposta: {response.text[:200]}")
                            return {'status': 'failed', 'reason': f'Non-JSON response from passtheimage: {response.status_code}'}

                        if response.status_code != 200 or response_data.get('status_code') != 200:
                            error_message = response_data.get('error', {}).get('message', 'Unknown error')
                            error_code = response_data.get('error', {}).get('code', 'Unknown code')
                            console.print(f"[yellow]Passtheimage falhou (código: {error_code}): {error_message}")
                            return {'status': 'failed', 'reason': f'passtheimage upload failed: {error_message}'}

                        if 'image' in response_data:
                            img_url = response_data['image']['url']
                            raw_url = response_data['image']['url']
                            web_url = response_data['image']['url_viewer']

                        if not img_url or not raw_url or not web_url:
                            console.print(f"[yellow]Dados de URL incompletos na resposta do passtheimage: {response_data}")
                            return {'status': 'failed', 'reason': 'Incomplete URL data from passtheimage'}

                        return {'status': 'success', 'img_url': img_url, 'raw_url': raw_url, 'web_url': web_url, 'local_file_path': image}

            except httpx.TimeoutException:
                console.print("[red]Solicitação ao passtheimage expirou após 60 segundos")
                return {'status': 'failed', 'reason': 'Request timed out'}
            except httpx.RequestError as e:
                console.print(f"[red]Solicitação ao passtheimage falhou: {e}")
                return {'status': 'failed', 'reason': str(e)}
            except ValueError as e:
                console.print(f"[red]Resposta JSON inválida do passtheimage: {e}")
                return {'status': 'failed', 'reason': 'Invalid JSON response'}
            except Exception as e:
                console.print(f"[red]Erro inesperado no passtheimage: {str(e)}")
                return {'status': 'failed', 'reason': f'Unexpected error: {str(e)}'}

        if img_url and raw_url and web_url:
            return {
                'status': 'success',
                'img_url': img_url,
                'raw_url': raw_url,
                'web_url': web_url,
                'local_file_path': image
            }
        else:
            return {
                'status': 'failed',
                'reason': f"Failed to upload image to {img_host}. No URLs received."
            }

    except Exception as e:
        return {
            'status': 'failed',
            'reason': str(e)
        }


# Global Thread Pool Executor for better thread control
thread_pool = ThreadPoolExecutor(max_workers=10)


async def upload_screens(meta, screens, img_host_num, i, total_screens, custom_img_list, return_dict, retry_mode=False, max_retries=3):
    if 'image_list' not in meta:
        meta['image_list'] = []
    if meta['debug']:
        upload_start_time = time.time()

    os.chdir(f"{meta['base_dir']}/tmp/{meta['uuid']}")
    initial_img_host = config['DEFAULT'][f'img_host_{img_host_num}']
    img_host = meta['imghost']
    if meta['debug']:
        console.print(f"[blue]Usando host de imagem: {img_host} (configurado: {initial_img_host})[/blue]")
    using_custom_img_list = isinstance(custom_img_list, list) and bool(custom_img_list)

    if 'image_sizes' not in meta:
        meta['image_sizes'] = {}

    # Handle image selection
    if using_custom_img_list:
        image_glob = custom_img_list
        existing_images = []
        existing_count = 0
    else:
        image_patterns = ["*.png", ".[!.]*.png"]
        image_glob = []
        for pattern in image_patterns:
            glob_results = await asyncio.to_thread(glob.glob, pattern)
            image_glob.extend(glob_results)

        unwanted_patterns = ["FILE*", "PLAYLIST*", "POSTER*"]
        unwanted_files = set()
        for pattern in unwanted_patterns:
            glob_results = await asyncio.to_thread(glob.glob, pattern)
            unwanted_files.update(glob_results)
            if pattern.startswith("FILE") or pattern.startswith("PLAYLIST") or pattern.startswith("POSTER"):
                hidden_pattern = "." + pattern
                hidden_glob_results = await asyncio.to_thread(glob.glob, hidden_pattern)
                unwanted_files.update(hidden_glob_results)

        image_glob = [file for file in image_glob if file not in unwanted_files]
        image_glob = list(set(image_glob))

        # Sort images by numeric suffix
        def extract_numeric_suffix(filename):
            match = re.search(r"-(\d+)\.png$", filename)
            return int(match.group(1)) if match else float('inf')

        image_glob.sort(key=extract_numeric_suffix)

        if meta['debug']:
            console.print("globs de imagem (ordenados):", image_glob)

        existing_images = [img for img in meta['image_list'] if img.get('img_url') and img.get('web_url')]
        existing_count = len(existing_images)

    # Determine images needed
    images_needed = total_screens - existing_count if not retry_mode else total_screens
    if meta['debug']:
        console.print(f"[blue]Imagens existentes: {existing_count}, Necessárias: {images_needed}, Total de telas: {total_screens}[/blue]")

    if existing_count >= total_screens and not retry_mode and img_host == initial_img_host and not using_custom_img_list:
        console.print(f"[yellow]Ignorando upload: {existing_count} existentes, {total_screens} exigidas.")
        return meta['image_list'], total_screens

    upload_tasks = [
        (index, image, img_host, config, meta)
        for index, image in enumerate(image_glob[:images_needed])
    ]

    # Concurrency Control
    default_pool_size = len(upload_tasks)
    host_limits = {"onlyimage": 6, "ptscreens": 6, "lensdump": 1, "passtheimage": 6}
    pool_size = host_limits.get(img_host, default_pool_size)
    max_workers = min(len(upload_tasks), pool_size)
    semaphore = asyncio.Semaphore(max_workers)

    # Track running tasks for cancellation
    running_tasks = set()

    async def async_upload(task, max_retries=3):
        """Upload image with concurrency control and retry logic."""
        index, *task_args = task
        retry_count = 0

        async with semaphore:
            while retry_count <= max_retries:
                future = None
                try:
                    future = asyncio.create_task(upload_image_task(task_args))
                    running_tasks.add(future)

                    try:
                        result = await asyncio.wait_for(future, timeout=60.0)
                        running_tasks.discard(future)

                        if result.get('status') == 'success':
                            return (index, result)
                        else:
                            reason = result.get('reason', 'Unknown error')
                            if "duplicate" in reason.lower():
                                console.print(f"[yellow]Ignorando host por imagem duplicada {index}: {reason}[/yellow]")
                                return None
                            elif "api key" in reason.lower():
                                console.print(f"[red]Erro de API key para {img_host}. Abortando novas tentativas.[/red]")
                                return None
                            if retry_count < max_retries:
                                retry_count += 1
                                console.print(f"[yellow]Tentativa {retry_count}/{max_retries} para a imagem {index}: {reason}[/yellow]")
                                await asyncio.sleep(1.1 * retry_count)
                                continue
                            else:
                                console.print(f"[red]Falha ao enviar a imagem {index} após {max_retries} tentativas: {reason}[/red]")
                                return None

                    except asyncio.TimeoutError:
                        console.print(f"[red]Tarefa de upload {index} excedeu 60 segundos[/red]")
                        if future in running_tasks:
                            future.cancel()
                            running_tasks.discard(future)

                        if retry_count < max_retries:
                            retry_count += 1
                            console.print(f"[yellow]Tentativa {retry_count}/{max_retries} para a imagem {index} após timeout[/yellow]")
                            await asyncio.sleep(1.1 * retry_count)
                            continue
                        return None

                except asyncio.CancelledError:
                    console.print(f"[red]Tarefa de upload {index} cancelada.[/red]")
                    if future and future in running_tasks:
                        future.cancel()
                        running_tasks.discard(future)
                    return None

                except Exception as e:
                    console.print(f"[red]Erro durante o upload da imagem {index}: {str(e)}[/red]")
                    if retry_count < max_retries:
                        retry_count += 1
                        console.print(f"[yellow]Tentativa {retry_count}/{max_retries} para a imagem {index}: {str(e)}[/yellow]")
                        await asyncio.sleep(1.5 * retry_count)
                        continue
                    else:
                        console.print(f"[red]Erro durante o upload da imagem {index} após {max_retries} tentativas: {str(e)}[/red]")
                        return None

    try:
        max_retries = 3
        try:
            upload_results = await asyncio.gather(*[async_upload(task, max_retries) for task in upload_tasks])
            results = [res for res in upload_results if res is not None]
            results.sort(key=lambda x: x[0])
        except Exception as e:
            console.print(f"[red]Erro durante os uploads: {str(e)}[/red]")

        successfully_uploaded = [(index, result) for index, result in results if result['status'] == 'success']
        if meta['debug']:
            console.print(f"[blue]{len(successfully_uploaded)} de {len(upload_tasks)} uploads concluídos com sucesso.[/blue]")

        # Ensure we only switch hosts if necessary
        if meta['debug']:
            console.print(f"[blue]Verificando host atual: {img_host}, Host inicial: {initial_img_host}[/blue]")
            console.print(f"[blue]retry_mode: {retry_mode}, using_custom_img_list: {using_custom_img_list}[/blue]")
            console.print(f"[blue]successfully_uploaded={len(successfully_uploaded)}, meta['image_list']={len(meta['image_list'])}, cutoff={meta.get('cutoff', 1)}[/blue]")
        if (len(successfully_uploaded) + len(meta['image_list'])) < meta.get('cutoff', 1) and not retry_mode and img_host == initial_img_host and not using_custom_img_list:
            img_host_num += 1
            if f'img_host_{img_host_num}' in config['DEFAULT']:
                meta['imghost'] = config['DEFAULT'][f'img_host_{img_host_num}']
                console.print(f"[cyan]Alternando para o próximo host de imagem: {meta['imghost']}[/cyan]")

                gc.collect()
                return await upload_screens(meta, screens, img_host_num, i, total_screens, custom_img_list, return_dict, retry_mode=True)
            else:
                console.print("[red]Não há mais hosts de imagem disponíveis. Abortando processo de upload.")
                return meta['image_list'], len(meta['image_list'])

        # Process and store successfully uploaded images
        new_images = []
        for index, upload in successfully_uploaded:
            raw_url = upload['raw_url']
            new_image = {
                'img_url': upload['img_url'],
                'raw_url': raw_url,
                'web_url': upload['web_url']
            }
            new_images.append(new_image)
            if not using_custom_img_list and raw_url not in {img['raw_url'] for img in meta['image_list']}:
                if meta['debug']:
                    console.print(f"[blue]Adicionando {raw_url} a image_list")
                meta['image_list'].append(new_image)
                local_file_path = upload.get('local_file_path')
                if local_file_path:
                    image_size = os.path.getsize(local_file_path)
                    meta['image_sizes'][raw_url] = image_size

        if len(new_images) and len(new_images) > 0:
            if not using_custom_img_list:
                console.print(f"[green]{len(new_images)} imagens obtidas e enviadas com sucesso.")
        else:
            raise Exception("Nenhuma imagem enviada. Configure hosts de imagem adicionais ou use um -ih diferente")

        if not using_custom_img_list:
            console.print(f"[green]{len(new_images)} imagens obtidas e enviadas com sucesso.")

        if meta['debug']:
            console.print(f"Uploads de screenshots processados em {time.time() - upload_start_time:.4f} segundos")

        return (new_images, len(new_images)) if using_custom_img_list else (meta['image_list'], len(successfully_uploaded))

    except asyncio.CancelledError:
        console.print("\n[red]Processo de upload interrompido! Cancelando tarefas...[/red]")

        # Cancel running tasks
        for task in running_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        return meta['image_list'], len(meta['image_list'])

    finally:
        # Cleanup
        thread_pool.shutdown(wait=True)
        gc.collect()


async def imgbox_upload(chdir, image_glob, meta, return_dict):
    try:
        os.chdir(chdir)
        image_list = []

        async with pyimgbox.Gallery(thumb_width=350, square_thumbs=False) as gallery:
            for image in image_glob:
                try:
                    async for submission in gallery.add([image]):
                        if not submission['success']:
                            console.print(f"[red]Erro ao enviar para imgbox: [yellow]{submission['error']}[/yellow][/red]")
                        else:
                            web_url = submission.get('web_url')
                            img_url = submission.get('thumbnail_url')
                            raw_url = submission.get('image_url')
                            if web_url and img_url and raw_url:
                                image_dict = {
                                    'web_url': web_url,
                                    'img_url': img_url,
                                    'raw_url': raw_url
                                }
                                image_list.append(image_dict)
                            else:
                                console.print(f"[red]URLs incompletas recebidas para a imagem: {image}")
                except Exception as e:
                    console.print(f"[red]Erro durante o upload de {image}: {str(e)}")

        return_dict['image_list'] = image_list
        return image_list

    except Exception as e:
        console.print(f"[red]Ocorreu um erro ao enviar imagens para o imgbox: {str(e)}")
        return []
