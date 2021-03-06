%define default_access_key_id     nil
%define default_secret_access_key nil
#%define default_access_key_id     'your_AWS_ACCESS_KEY_ID'
#%define default_secret_access_key 'your_AWS_SECRET_KEY'

Summary: attach-eni
Name: attach-eni
Version: 0.1.0
Release: 1
License: BSD

BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildArch: noarch

%description
attach-eni

%install
rm -rf $RPM_BUILD_ROOT
install -d -m755 $RPM_BUILD_ROOT%{_sbindir}

cat <<'EOF' > $RPM_BUILD_ROOT%{_sbindir}/attach-eni
#!/usr/bin/env ruby
require 'cgi'
require 'base64'
require 'net/https'
require 'openssl'
require 'optparse'
require 'rexml/document'

Net::HTTP.version_1_2

class EC2Client
  API_VERSION = '2012-07-20'
  SIGNATURE_VERSION = 2
  SIGNATURE_ALGORITHM = :SHA256
  WAIT_LIMIT = 99
  WAIT_INTERVAL = 0.3

  def initialize(accessKeyId, secretAccessKey, endpoint = nil)
    @accessKeyId = accessKeyId
    @secretAccessKey = secretAccessKey

    unless endpoint
      endpoint = Net::HTTP.get('169.254.169.254', '/latest/meta-data/placement/availability-zone')
      endpoint.sub!(/[a-z]\Z/i, '')
    end

    @endpoint = endpoint

    if /\A[^.]+\Z/ =~ @endpoint
      @endpoint = "ec2.#{@endpoint}.amazonaws.com"
    end
  end

  def attach_interface(if_id, dev_idx = nil, instance_id = nil)
    dev_idx = 1 unless dev_idx

    unless instance_id
      instance_id = Net::HTTP.get('169.254.169.254', '/latest/meta-data/instance-id')
    end

    check_own_attached(if_id, instance_id)
    detach_interface(if_id, :force) rescue nil
    wait_for_detaching(if_id)

    source = query('AttachNetworkInterface', 'NetworkInterfaceId' => if_id, 'InstanceId' => instance_id, 'DeviceIndex' => dev_idx)

    errors = []

    REXML::Document.new(source).each_element('//Errors/Error') do |element|
      code = element.text('Code')
      message = element.text('Message')
      errors << "#{code}:#{message}"
    end

    raise errors.join(', ') unless errors.empty?
  end

  private

  def check_own_attached(if_id, instance_id)
    interfaces = describe_interfaces(if_id)

    if not interfaces or interfaces.empty?
      raise 'interface was not found'
    end

    interface = interfaces.first

    if (interface['attachment'] || {})['instanceId'] == instance_id
      raise 'interface is already attached'
    end
  end

  def wait_for_detaching(if_id)
    WAIT_LIMIT.times do
      interfaces = describe_interfaces(if_id)

      if not interfaces or interfaces.empty?
        raise 'interface was not found'
      end

      interface = interfaces.first

      return if interface['status'] == 'available'

      sleep WAIT_INTERVAL
    end

    raise 'cannot detach interface'
  end

  def detach_interface(if_id, force = false)
    interfaces = describe_interfaces(if_id)

    if not interfaces or interfaces.empty?
      raise 'interface was not found'
    end

    interface = interfaces.first
    attachment_id = (interface['attachment'] || {})['attachmentId'] || ''

    if attachment_id.empty?
      raise 'attachmentId was not found'
    end

    params = {'AttachmentId' => attachment_id}
    params['Force'] = true if force
    source = query('DetachNetworkInterface', params)

    errors = []

    REXML::Document.new(source).each_element('//Errors/Error') do |element|
      code = element.text('Code')
      message = element.text('Message')
      errors << "#{code}:#{message}"
    end

    raise errors.join(', ') unless errors.empty?
  end

  def describe_interfaces(if_id = nil)
    dev_idx = 1 unless dev_idx
    params = {}

    if if_id
      params.update('Filter.1.Name' => 'network-interface-id', 'Filter.1.Value' => if_id)
    end

    source = query('DescribeNetworkInterfaces', params)
    interfaces = []

    items = REXML::Document.new(source).get_elements('//networkInterfaceSet/item')
    walk_item_list(items, interfaces)

    return interfaces
  end

  def walk_item_list(list, ary)
    list.each do |item|
      hash = {}
      walk_item(item, hash)
      ary << hash
    end
  end

  def walk_item(item, hash)
    return unless item.has_elements?

    item.elements.each do |child|
      if child.has_elements?
        if child.elements.all? {|i| i.name =~ /\Aitem\Z/i }
          hash[child.name] = nested = []
          walk_item_list(child.elements, nested)
        else
          hash[child.name] = nested = {}
          walk_item(child, nested)
        end
      else
        hash[child.name] = child.text
      end
    end
  end

  def query(action, params = {})
    params = {
      :Action           => action,
      :Version          => API_VERSION,
      :Timestamp        => Time.now.getutc.strftime('%Y-%m-%dT%H:%M:%SZ'),
      :SignatureVersion => SIGNATURE_VERSION,
      :SignatureMethod  => "Hmac#{SIGNATURE_ALGORITHM}",
      :AWSAccessKeyId   => @accessKeyId,
    }.merge(params)

    signature = aws_sign(params)
    params[:Signature] = signature

    https = Net::HTTP.new(@endpoint, 443)
    https.use_ssl = true
    https.verify_mode = OpenSSL::SSL::VERIFY_NONE

    https.start do |w|
      req = Net::HTTP::Post.new('/',
        'Host' => @endpoint,
        'Content-Type' => 'application/x-www-form-urlencoded'
      )

      req.set_form_data(params)
      res = w.request(req)

      res.body
    end
  end

  def aws_sign(params)
    params = params.sort_by {|a, b| a.to_s }.map {|k, v| "#{CGI.escape(k.to_s)}=#{CGI.escape(v.to_s)}" }.join('&')
    string_to_sign = "POST\n#{@endpoint}\n/\n#{params}"
    digest = OpenSSL::HMAC.digest(OpenSSL::Digest.const_get(SIGNATURE_ALGORITHM).new, @secretAccessKey, string_to_sign)
    Base64.encode64(digest).gsub("\n", '')
  end
end # EC2Client

# main
access_key = nil
secret_key = nil
endpoint = nil
if_id = nil
dev_idx = nil
instance_id = nil

ARGV.options do |opt|
  begin
    opt.on('-k', '--access-key ACCESS_KEY') {|v| access_key = v }
    opt.on('-s', '--secret-key SECRET_KEY') {|v| secret_key = v }
    opt.on('-r', '--region REGION') {|v| endpoint = v }
    opt.on('-n', '--network-if-id IF_ID') {|v| if_id = v }
    opt.on('-d', '--device-index INDEX') {|v| dev_idx = v }
    opt.on('-i', '--instance-id INSTANCE_ID') {|v| instance_id = v }
    opt.parse!

    access_key ||= %{default_access_key_id}
    secret_key ||= %{default_secret_access_key}

    unless access_key and secret_key and if_id
      puts opt.help
      exit 1
    end
  rescue => e
    $stderr.puts e
    exit 1
  end
end

ec2cli = EC2Client.new(access_key, secret_key, endpoint)
ec2cli.attach_interface(if_id, dev_idx, instance_id)
EOF

chmod 700 $RPM_BUILD_ROOT%{_sbindir}/attach-eni

%files
%attr(0700,root,root) %{_sbindir}/attach-eni
