#!/usr/bin/env python2

from __future__ import print_function

import base64
import binascii
import cgi  # cgi.parse_header
import datetime
import hashlib
import logging
import os
import socket
import sys
import time
import urllib2
import urlparse
from getpass import getpass
from optparse import OptionParser
from urllib import FancyURLopener, urlencode

from selenium import webdriver
from selenium.common.exceptions import ElementNotVisibleException
from selenium.webdriver.support.ui import Select


def login_audible(driver, options, username, password, base_url, lang):
    # Step 1
    if '@' in username:  # Amazon login using email address
        login_url = "https://www.amazon.com/ap/signin?"
    else:  # Audible member login using username (untested!)
        login_url = "https://www.audible.com/sign-in/%s" % (
            "ref=ap_to_private?forcePrivateSignIn=true&rdPath=https%3A%2F%2Fwww.audible.com%2F%3F"
        )
    if lang != "us":  # something more clever might be needed
        login_url = login_url.replace('.com', "." + lang)
        base_url = base_url.replace('.com', "." + lang)
    player_id = base64.encodestring(hashlib.sha1("").digest()).rstrip(
    )  # keep this same to avoid hogging activation slots
    if options.player_id:
        player_id = base64.encodestring(binascii.unhexlify(options.player_id)).rstrip()
    logging.debug("[*] Player ID is %s", player_id)
    payload = {
        'openid.ns':
        'http://specs.openid.net/auth/2.0',
        'openid.identity':
        'http://specs.openid.net/auth/2.0/identifier_select',
        'openid.claimed_id':
        'http://specs.openid.net/auth/2.0/identifier_select',
        'openid.mode':
        'logout',
        'openid.assoc_handle':
        'amzn_audible_' + lang,
        'openid.return_to':
        base_url + "player-auth-token" +
        "?playerType=%s&playerId=%s=&bp_ua=y&playerModel=%s&playerManufacturer=%s" %
        ("software", player_id, "Desktop", "Audible")
    }
    query_string = urlencode(payload)
    url = login_url + query_string
    logging.info("Opening Audible for language %s", lang)
    driver.get(base_url + '?ipRedirectOverride=true')
    logging.info("Logging in to Amazon/Audible")
    driver.get(url)
    search_box = driver.find_element_by_id('ap_email')
    search_box.send_keys(username)
    search_box = driver.find_element_by_id('ap_password')
    search_box.send_keys(password)
    if os.getenv("DEBUG") or options.debug:
        # enable if you hit CAPTCHA or 2FA or other "security" screens
        logging.warning(
            "[!] Running in DEBUG mode. You will need to login in a semi-automatic way, "
            "wait for the login screen to show up ;)"
        )
        time.sleep(22)
    else:
        search_box.submit()


def configure_browser(options):
    logging.info("Configuring browser")

    web_opts = webdriver.ChromeOptions()

    # Chrome user agent will download files for us
    #web_opts.add_argument(
    #    "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    #    "Chrome/53.0.2785.116 Safari/537.36")

    if not options.just_download:
        # This user agent will give us files w. download info
        web_opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; AS; rv:11.0) like Gecko"
        )
    else:
        # This one will just download
        web_opts.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_4) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36"
        )
    chromePrefs = {
        "profile.default_content_settings.popups": "0",
        "download.default_directory": options.dw_dir
    }
    web_opts.add_experimental_option("prefs", chromePrefs)

    if sys.platform == 'win32':
        chromedriver_path = "chromedriver.exe"
    else:
        chromedriver_path = "./chromedriver"

    logging.info("Starting browser")

    driver = webdriver.Chrome(chrome_options=web_opts, executable_path=chromedriver_path)

    return driver


class HeadRequest(urllib2.Request):

    def get_method(self):
        return "HEAD"


class LyingFancyURLopener(FancyURLopener):

    def __init__(self):
        self.version = 'Audible ADM 6.6.0.19;Windows Vista Service Pack 1 Build 7601'
        FancyURLopener.__init__(self)


def wait_for_download_or_die(datafile):
    retry = 0
    dw_sleep = 5
    while retry < 5 and not os.path.isfile(datafile):
        logging.info(
            "%s not downloaded yet, sleeping %s seconds (retry #%s)", datafile, dw_sleep, retry
        )
        retry = retry + 1
        time.sleep(dw_sleep)
    if not os.path.isfile(datafile):
        logging.critical(
            "Chrome used more than %s seconds to download %s, something is wrong, exiting",
            dw_sleep * retry, datafile
        )
        sys.exit(1)


def print_progress(block_count, block_size, total_size):
    #The hook will be passed three arguments;
    #    a count of blocks transferred so far,
    #    a block size in bytes,
    #    and the total size of the file. (may be -1, ignored)

    prev_bytes_complete = (block_count - 1) * block_size
    prev_percent = float(prev_bytes_complete) / float(total_size) * 100.0
    prev_progress = "%.0f" % prev_percent

    bytes_complete = block_count * block_size
    percent = float(bytes_complete) / float(total_size) * 100.0
    progress = "%.0f" % percent

    if (progress != prev_progress and
            (block_count == 0 or
             int(progress) % 5 == 0 or
             int(progress) >= 100)
       ):
        logging.info("Download: %s%% (%s of %s bytes)", progress, bytes_complete, total_size)


def download_file(datafile, scraped_title, book, page, maxpage):
    # pylint: disable=too-many-branches,too-many-statements
    with open(datafile) as f:
        logging.info("Parsing %s, creating download url", datafile)
        lines = f.readlines()

    dw_options = urlparse.parse_qs(lines[0])
    title = dw_options["title"][0]
    if title != scraped_title:
        logging.info("Found real title: %s", title)
    logging.info("Parsed data for book '%s'", title)

    url = dw_options["assemble_url"][0]

    params = {}
    for param in ["user_id", "product_id", "codec", "awtype", "cust_id"]:
        if dw_options[param][0] == "LC_64_22050_stereo":
            params[param] = "LC_64_22050_ster"
        else:
            params[param] = dw_options[param][0]

    url_parts = list(urlparse.urlparse(url))
    query = dict(urlparse.parse_qsl(url_parts[4]))
    query.update(params)

    url_parts[4] = urlencode(query)

    url = urlparse.urlunparse(url_parts)
    logging.info("Book URL: %s", url)

    logging.info("Downloading file data")
    request_head = HeadRequest(url)
    request_head.add_header(
        'User-Agent', 'Audible ADM 6.6.0.19;Windows Vista Service Pack 1 Build 7601'
    )
    #request_head.add_header('User-Agent',
    #   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_4) AppleWebKit/537.36 "
    #   "(KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36")

    tries = 0
    head_ok = False
    while not head_ok:
        try:
            head = urllib2.urlopen(request_head)
            head_ok = True
        except urllib2.HTTPError:
            if tries < 5:
                logging.info("HEAD request failed(HTTP), sleeping and retrying")
                tries = tries + 1
                time.sleep(60)
            else:
                raise
        except socket.error:
            if tries < 5:
                logging.info("HEAD request failed (socket), sleeping and retrying")
                tries = tries + 1
                time.sleep(60)
            else:
                raise

    _, par = cgi.parse_header(head.info().dict['content-disposition'])
    filename = par['filename'].split("_")[0]
    filename = filename + "." + par['filename'].split(".")[-1]
    size = head.info().dict['content-length']

    logging.info("Filename: %s", filename)
    logging.info("Size: %s", size)

    path = "%s%s" % (opts.dw_dir, filename)

    logging.info("Book %s of 20 on page %s of %s", book, page, maxpage)

    if os.path.isfile(path):
        logging.info("File %s exist, checking size", path)
        if int(size) == os.path.getsize(path):
            logging.info("File %s has correct size, not downloading", path)
            time.sleep(60)  # sleep a minute to not be throttled
            return False
        else:
            logging.warning("File %s had unexpected size, downloading", path)
    else:
        logging.info("File %s does not exist, downloading", path)

    we_are_really_doing_this = True
    if we_are_really_doing_this:
        opener = LyingFancyURLopener()
        opener.retrieve(url, path, reporthook=print_progress)
        #local_filename, headers = opener.retrieve(url, path, reporthook=print_progress)
        #local_filename, headers = urlretrieve(url, path, reporthook=print_progress)

        #import pdb; pdb.set_trace()

        #filename = ""
        #try:
        #    val, par = cgi.parse_header(headers.dict['content-disposition'])
        #    filename = par['filename'].split("_")[0]
        #    filename = filename + "." +  par['filename'].split(".")[-1]
        #except KeyError:
        #    import pdb; pdb.set_trace()

        #logging.info("Filename: %s" % filename)
        #logging.info("Size: %s" % size)

        #path = "%s%s" % (options.dw_dir, filename)
        #os.rename(local_filename,path)
        logging.info("Completed download of '%s' to %s", title, path)
    else:
        logging.info("Completed download of '%s' to %s (not really)", title, path)
    return True


def wait_for_file_delete(datafile):
    os.remove(datafile)
    retry = 0
    dw_sleep = 2
    while retry < 5 and os.path.isfile(datafile):
        logging.info("%s not deleted, sleeping %s seconds (retry #%s)", datafile, dw_sleep, retry)
        retry = retry + 1
        time.sleep(dw_sleep)
    if os.path.isfile(datafile):
        logging.critical(
            "OS used more than %s seconds to delete %s, something is wrong, exiting", datafile,
            dw_sleep * retry
        )
        sys.exit(1)


def wait_for_download_done(title):
    ok_punct = [c for c in "-.[]"]
    file_pre = "".join(x for x in title if x.isalnum() or x in ok_punct)
    expected_prefixes = [file_pre, "{}{}".format(file_pre, "Unabridged")]
    dl_fname = None
    correct_prefix = None

    # Wait for the download to start
    retries_left = 5
    while retries_left and not dl_fname:
        retries_left -= 1
        files = os.listdir(opts.dw_dir)
        for fname in files:
            for prefix in expected_prefixes:
                if fname.startswith("{}_".format(prefix)):
                    dl_fname = fname
                    correct_prefix = prefix
                    logging.info("File '%s' is downloading...", fname)
                    break

        if not dl_fname:
            logging.info("Title '%s' still not downloading, waiting...", title)
            time.sleep(10)

    if not dl_fname and retries_left <= 0:
        logging.critical("Title '%s' took too long to start downloading, panicing.", title)
        sys.exit(1)

    if not dl_fname.endswith("aax.crdownload"):
        logging.warn("Unexpected file download suffix in progress '%s", dl_fname)

    # Wait for the download to actually finish
    retries_left = 30
    while os.path.exists(os.path.join(opts.dw_dir, dl_fname)) and retries_left:
        retries_left -= 1
        time.sleep(20)
        logging.info("File '%s' still downloading, waiting...", dl_fname)

    if retries_left <= 0:
        logging.critical("'%s' (%s) took too long to download, panicing.", title, dl_fname)
        sys.exit(1)

    expected_fname = dl_fname[:-len(".crdownload")]
    corrected_fname = "{}.aax".format(correct_prefix)
    if os.path.exists(os.path.join(opts.dw_dir, expected_fname)):
        logging.info(
            "File '%s' download complete, renaming to '%s'", expected_fname, corrected_fname
        )
        os.rename(
            os.path.join(opts.dw_dir, expected_fname), os.path.join(opts.dw_dir, corrected_fname)
        )
    else:
        logging.critical("Finished download but file '%s' not found, panicing!", expected_fname)
        sys.exit(1)


def download_files_on_page(driver, page, maxpage, resume_at, debug):
    # pylint: disable=too-many-nested-blocks
    books_downloaded = 0

    trs = driver.find_elements_by_tag_name("tr")
    for tr in trs:
        titles = tr.find_elements_by_name("tdTitle")
        for title_a in titles:
            #for a in td.find_elements_by_class_name("adbl-prod-title"):
            title = title_a.text.strip()
            if title != "":
                logging.info("Found book: '%s'", title)
                if not debug:
                    if not resume_at or resume_at in title:
                        resume_at = None
                        #for author_ in tr.find_elements_by_class_name("adbl-library-item-author"):
                        #    print("Author (%s): '%s'" % (c, author_.text.strip()))
                        for download_a in tr.find_elements_by_class_name("adbl-download-it"):
                            #print("Download-title (%s): %s" %
                            # (c, download_a.get_attribute("title").strip()))
                            logging.info("Clicking download link for %s", title)
                            try:
                                download_a.click()
                                if not opts.just_download:
                                    logging.info(
                                        "Waiting for Chrome to complete download of datafile"
                                    )
                                    time.sleep(1)
                                    datafile = "%s%s" % (opts.dw_dir, "admhelper")
                                    wait_for_download_or_die(datafile)
                                    logging.info("Datafile downloaded")
                                    books_downloaded = books_downloaded + 1
                                    download_file(datafile, title, books_downloaded, page, maxpage)
                                    wait_for_file_delete(datafile)
                                    time.sleep(1)
                                else:
                                    wait_for_download_done(title)
                                    books_downloaded = books_downloaded + 1
                            except ElementNotVisibleException:
                                logging.exception("Download button Not Visible!")
                    else:
                        books_downloaded = books_downloaded + 1
                        logging.info(
                            "Skipping book '%s', looking for match with '%s'", title, resume_at
                        )
                        time.sleep(1)
                else:
                    books_downloaded = books_downloaded + 1
                    logging.info("Debug, no download")
                    time.sleep(1)

                logging.info("looping through all download in specific TR complete")
        #logging.info("looping through all tdTitle in spesific TR complete")
    logging.info("Downloaded %s books from this page", books_downloaded)
    return (books_downloaded, resume_at)


def configure_audible_library(driver, lang):
    logging.info("Opening Audible library")
    lib_url = "https://www.audible.com/lib"
    if lang != "us":
        lib_url = lib_url.replace('.com', "." + lang)

    driver.get(lib_url)
    time.sleep(2)

    logging.info("Selecting books from 'All Time'")
    select = Select(driver.find_element_by_id("adbl_time_filter"))
    select.select_by_value("all")
    time.sleep(5)

    # Make sure we are getting the ENHANCED format
    # u'ENHANCED' u'MP332' u'ACELP16' u'ACELP85'
    s = Select(driver.find_element_by_id("adbl_select_preferred_format"))
    if len(s.all_selected_options) == 1:
        if s.all_selected_options[0].get_attribute("value").strip() == "ENHANCED":
            logging.info("Selected format was ENHANCED, continuing")
        else:
            logging.info(
                "Format was '%s', selecting 'ENHANCED'",
                s.all_selected_options[0].get_attribute("value")
            )
            for opt in s.options:
                if opt.get_attribute("value") == "ENHANCED":
                    opt.click()
                    time.sleep(5)
    else:
        logging.critical("Got more than one adbl_select_preferred_format.all_selected_options")
        sys.exit(1)

    # Comment out this in hope of not hitting download limit as fast
    if not 'adbl-sort-down' in driver.find_element_by_id("SortByLength").get_attribute("class"):
        logging.info("Sorting downloads by shortest to longest")
        driver.find_element_by_id("SortByLength").click()
        time.sleep(10)
    else:
        logging.info("Downloads were already sorted by shortest to longest, continuing")


def loop_pages(driver, options):
    maxpage = 1
    for link in driver.find_elements_by_class_name("adbl-page-link"):
        maxpage = max(maxpage, int(link.text))

    books_downloaded = 0
    resume_at = options.resume_book if options.resume_book else None

    logging.info("Found %s pages of books", maxpage)
    for pagenumz in range(maxpage):
        pagenum = pagenumz + 1
        if options.skip_to_page and pagenum < options.skip_to_page:
            logging.info("Skipping page #%s", pagenum)
        else:
            logging.info("Scrolling to bottom of page to force loading of content")
            for _ in range(4):
                # Page is not loaded before we scroll
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

            logging.info("Downloading books on page %s", pagenum)
            (new_downloads, resume_at) = download_files_on_page(
                driver, pagenum, maxpage, resume_at, debug=False
            )
            books_downloaded += new_downloads
            time.sleep(5)

        found_next = False
        logging.info("Looking for link to next page (page %s)", pagenum + 1)
        lis = driver.find_elements_by_class_name("adbl-pagination")
        for li in lis:
            ls = li.find_elements_by_class_name("adbl-link")
            for l in ls:
                #if l.text.strip() == "%s" % ((pagenum + 1),):
                if l.text.strip().lower() == "next":
                    logging.info("Clicking link for page NEXT")
                    #logging.info("Clicking link for page %s" % ((pagenum + 1),))
                    found_next = True
                    l.click()
                    time.sleep(3)
                    break
            if found_next:
                break

    logging.info("Downloaded or skipped a total of %s books", books_downloaded)


if __name__ == "__main__":
    parser = OptionParser(usage="Usage: %prog [options]", version="%prog 0.2")
    parser.add_option(
        "-d",
        "--debug",
        action="store_true",
        dest="debug",
        default=False,
        help="run program in debug mode, enable for 2FA enabled accounts or for auth debugging"
    )
    parser.add_option(
        "-j",
        action="store_true",
        dest="just_download",
        default=False,
        help="Just download the files via Chrome click"
    )
    parser.add_option(
        "-l",
        "--lang",
        action="store",
        dest="lang",
        default="us",
        help="us (default) / de / fr",
    )
    parser.add_option(
        "-p",
        action="store",
        dest="player_id",
        default=None,
        help="Player ID in hex (optional)",
    )
    parser.add_option(
        "-s",
        action="store",
        dest="skip_to_page",
        type=int,
        help="Skip to page #, to avoid long wait resuming"
    )
    parser.add_option(
        "-r",
        action="store",
        dest="resume_book",
        type=str,
        help="string contained in book to resume with"
    )
    parser.add_option(
        "-w",
        action="store",
        dest="dw_dir",
        default="/tmp/audible",
        help="Download directory (must exist)",
    )
    parser.add_option(
        "--user",
        action="store",
        dest="username",
        default=None,
        help="Username (optional, will be asked for if not provied)",
    )
    parser.add_option(
        "--password",
        action="store",
        dest="password",
        default=None,
        help="Password (optional, will be asked for if not provied)",
    )

    dt = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    logging.basicConfig(
        format='%(levelname)s(#%(lineno)d):%(message)s',
        level=logging.INFO,
        filename="./audible-download-%s.log" % (dt)
    )
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

    (opts, args) = parser.parse_args()

    if not opts.dw_dir.endswith(os.path.sep):
        opts.dw_dir += os.path.sep

    if not os.path.exists(opts.dw_dir):
        logging.info("download directory doesn't exist, creating " + opts.dw_dir)
        os.makedirs(opts.dw_dir)

    if not os.access(opts.dw_dir, os.W_OK):
        logging.error("download directory " + opts.dw_dir + " not writable")
        sys.exit(1)

    if not opts.username:
        opts.username = raw_input("Username: ")
    if not opts.password:
        opts.password = getpass("Password: ")

    url_base = 'https://www.audible.com/'
    base_url_license = 'https://www.audible.com/'

    webdriver = configure_browser(opts)
    try:
        wait_for_file_delete("%s%s" % (opts.dw_dir, "admhelper"))
    except OSError:
        pass

    login_audible(webdriver, opts, opts.username, opts.password, url_base, opts.lang)
    configure_audible_library(webdriver, opts.lang)
    loop_pages(webdriver, opts)

    logging.info("Jobs done!")
    #driver.quit()
    #quit()
